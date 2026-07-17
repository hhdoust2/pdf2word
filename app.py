import streamlit as st
import pytesseract
from PIL import Image, ImageEnhance
from pdf2image import convert_from_path
import os
import time
import subprocess
import shutil
import gc
import concurrent.futures
import io

# تنظیمات اولیه تسرکت در لینوکس هاگینگ‌فیس (تست محلی ممکن است نیاز به آدرس‌دهی دستی داشته باشد)
# pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

def do_ocr_on_one_page(image_file_path, page_number):
    def improve_image_quality(img):
        gray = img.convert('L')
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(2.5)
        return enhanced

    def make_sharp(img):
        sharpener = ImageEnhance.Sharpness(img)
        sharp_img = sharpener.enhance(1.3)
        return sharp_img

    try:
        image = Image.open(image_file_path)
        better_image = improve_image_quality(image)
        final_image = make_sharp(better_image)
        extracted_text = pytesseract.image_to_string(final_image, lang='fas', config='--psm 3 --oem 3')
        image.close()
        better_image = None
        final_image = None
        del image, better_image, final_image
        
        try:
            os.remove(image_file_path)
        except:
            pass
            
        return {
            'page_num': page_number,
            'text_content': extracted_text.strip(),
            'character_count': len(extracted_text.strip()),
            'is_successful': True
        }
    except Exception as error:
        return {
            'page_num': page_number,
            'text_content': f"خطا در صفحه {page_number}: {str(error)}",
            'character_count': 0,
            'is_successful': False
        }

def find_pdf_pages(pdf_file_path):
    page_count = 0
    try:
        process = subprocess.Popen(['pdfinfo', pdf_file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        output, errors = process.communicate()
        if process.returncode == 0:
            for line in output.split('\n'):
                if 'Pages:' in line:
                    page_count = int(line.split(':')[1].strip())
                    break
        else:
            with open(pdf_file_path, 'rb') as f:
                page_count = len(convert_from_path(pdf_file_path, first_page=1, last_page=1))
    except Exception:
        try:
            images = convert_from_path(pdf_file_path)
            page_count = len(images)
        except Exception:
            page_count = 0
    return page_count

def convert_pdf_to_image_files(input_pdf_path, batch_size_for_processing=8, image_dpi_quality=350, progress_bar=None):
    def create_temp_directory():
        temp_directory_path = './temp_ocr_images'
        if os.path.exists(temp_directory_path):
            shutil.rmtree(temp_directory_path)
        os.makedirs(temp_directory_path)
        return temp_directory_path

    def save_images_to_disk(images_list, start_page_num, temp_dir):
        saved_paths = []
        counter = 0
        for single_image in images_list:
            page_number = start_page_num + counter
            file_name = f"page_{page_number:04d}.jpg"
            full_path = os.path.join(temp_dir, file_name)
            single_image.save(full_path, 'JPEG', quality=95, optimize=True)
            saved_paths.append((full_path, page_number))
            counter += 1
        return saved_paths

    def cleanup_memory(images_to_cleanup):
        for img in images_to_cleanup:
            del img
        del images_to_cleanup
        gc.collect()

    total_pages = find_pdf_pages(input_pdf_path)
    temp_folder = create_temp_directory()
    all_image_paths = []
    current_start_page = 1
    
    while current_start_page <= total_pages:
        current_end_page = current_start_page + batch_size_for_processing - 1
        if current_end_page > total_pages:
            current_end_page = total_pages
            
        if progress_bar:
            progress_bar.text(f"⏳ در حال تبدیل صفحات {current_start_page} تا {current_end_page} به عکس...")
            
        try:
            converted_images = convert_from_path(
                input_pdf_path,
                dpi=image_dpi_quality,
                first_page=current_start_page,
                last_page=current_end_page,
                fmt='jpeg',
                thread_count=4,
                use_cropbox=False
            )
            saved_image_paths = save_images_to_disk(converted_images, current_start_page, temp_folder)
            all_image_paths.extend(saved_image_paths)
            cleanup_memory(converted_images)
        except Exception as e:
            st.error(f"خطا در تبدیل صفحات به عکس: {e}")
            
        current_start_page = current_end_page + 1
    return all_image_paths, total_pages

# رابط کاربری تحت وب (Streamlit UI)
st.set_page_config(page_title="مبدل PDF به متن فارسی (OCR)", layout="centered")

st.markdown("""
    <style>
    .reportview-container { text-align: right; direction: RTL; }
    .stButton>button { width: 100%; background-color: #4CAF50; color: white; }
    </style>
""", unsafe_allow_html=True)

st.title("📝 مبدل نامحدود PDF اسکن‌شده به متن فارسی")
st.write("فایل PDF خود (تا ۵۰۰ صفحه) را آپلود کنید تا با بهترین الگوریتم‌های هوش مصنوعی متون آن را استخراج کنیم.")

uploaded_file = st.file_uploader("فایل PDF خود را انتخاب کنید", type=["pdf"])

if uploaded_file is not None:
    # ذخیره فایل آپلود شده به صورت موقت
    temp_pdf_path = "user_uploaded_input.pdf"
    with open(temp_pdf_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
        
    pdf_size_mb = os.path.getsize(temp_pdf_path) / (1024*1024)
    
    # تنظیمات خودکار بر اساس حجم فایل
    if pdf_size_mb < 5:
        image_quality_dpi = 400
        worker_threads_count = 3
    elif pdf_size_mb < 20:
        image_quality_dpi = 350
        worker_threads_count = 3
    else:
        image_quality_dpi = 300
        worker_threads_count = 2

    if st.button("🚀 شروع عملیات استخراج متن (OCR)"):
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        start_time = time.time()
        
        # ۱. تبدیل پی دی اف به تصاویر
        image_paths, total_pages = convert_pdf_to_image_files(
            temp_pdf_path, 
            image_dpi_quality=image_quality_dpi, 
            progress_bar=status_text
        )
        
        # ۲. اجرای فرآیند OCR به صورت موازی
        status_text.text("✍️ در حال استخراج متون فارسی از تصاویر (OCR)...")
        all_ocr_results = []
        
        processed_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_threads_count) as executor:
            future_to_page = {
                executor.submit(do_ocr_on_one_page, img_path, page_num): page_num 
                for img_path, page_num in image_paths
            }
            
            for future in concurrent.futures.as_completed(future_to_page):
                result = future.result()
                all_ocr_results.append(result)
                processed_count += 1
                # بروزرسانی نوار پیشرفت در وب‌سایت
                progress_bar.progress(processed_count / len(image_paths))
        
        # مرتب‌سازی نتایج بر اساس شماره صفحه
        all_ocr_results.sort(key=lambda x: x['page_num'])
        
        # ۳. تولید خروجی متنی فشرده شده برای دانلود
        output_data = io.StringIO()
        output_data.write("# نتایج OCR فارسی\n")
        output_data.write(f"# فایل مبدا: {uploaded_file.name}\n")
        output_data.write(f"# زمان پردازش: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        output_data.write("="*70 + "\n\n")
        
        successful_count = 0
        total_chars = 0
        
        for res in all_ocr_results:
            output_data.write(f"\n--- صفحه {res['page_num']} ---\n")
            output_data.write(res['text_content'])
            output_data.write("\n\n")
            if res['is_successful'] and res['character_count'] > 5:
                successful_count += 1
                total_chars += res['character_count']
                
        end_time = time.time()
        duration = end_time - start_time
        
        # پاکسازی فایل‌های موقت
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)
        if os.path.exists('./temp_ocr_images'):
            shutil.rmtree('./temp_ocr_images')
            
        # نمایش آمار و دکمه دانلود
        status_text.empty()
        progress_bar.empty()
        
        st.success(f"✅ عملیات با موفقیت پایان یافت!")
        st.info(f"⏱️ زمان کل: {duration:.1f} ثانیه | 📄 صفحات پردازش شده: {successful_count} از {total_pages} | 🔤 کل کاراکترها: {total_chars:,}")
        
        # دکمه دانلود مستقیم فایل متنی حاصل شده
        st.download_button(
            label="📥 دانلود فایل متنی استخراج شده (TXT)",
            data=output_data.getvalue(),
            file_name=f"OCR_{uploaded_file.name.replace('.pdf', '')}.txt",
            mime="text/plain"
        )
