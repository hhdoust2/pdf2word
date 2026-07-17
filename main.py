from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import pytesseract
from PIL import Image, ImageEnhance
from pdf2image import convert_from_path
import os
import shutil
import gc
import concurrent.futures
import time

app = FastAPI()

# تنظیمات CORS برای اتصال بدون مشکل سایت استاتیک شما به سرور رندر
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def do_ocr_on_one_page(image_file_path, page_number):
    try:
        image = Image.open(image_file_path)
        gray = image.convert('L')
        enhanced = ImageEnhance.Contrast(gray).enhance(2.5)
        final_image = ImageEnhance.Sharpness(enhanced).enhance(1.3)
        
        extracted_text = pytesseract.image_to_string(final_image, lang='fas', config='--psm 3 --oem 3')
        image.close()
        try: 
            os.remove(image_file_path)
        except: 
            pass
        return {'page_num': page_number, 'text_content': extracted_text.strip()}
    except Exception as e:
        return {'page_num': page_number, 'text_content': f"خطا در صفحه {page_number}: {str(e)}"}

@app.get("/")
def read_root():
    return {"status": "سرور پی‌دی‌اف خوان فارسی فعال است"}

@app.post("/process-pdf")
async def process_pdf(file: UploadFile = File(...)):
    temp_pdf = "input.pdf"
    with open(temp_pdf, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    temp_dir = "./temp_images"
    if os.path.exists(temp_dir): 
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    # تبدیل صفحات با کیفیت بهینه شده برای رم محدود سرور رایگان
    images = convert_from_path(temp_pdf, dpi=200, fmt='jpeg', thread_count=2)
    image_paths = []
    for i, img in enumerate(images):
        page_num = i + 1
        path = os.path.join(temp_dir, f"page_{page_num:04d}.jpg")
        img.save(path, 'JPEG', quality=85)
        image_paths.append((path, page_num))
    
    del images
    gc.collect()
    
    # پردازش موازی کنترل شده جهت پایداری بالا در ۵۰۰ صفحه
    all_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(do_ocr_on_one_page, path, num) for path, num in image_paths]
        for f in concurrent.futures.as_completed(futures):
            all_results.append(f.result())
            
    all_results.sort(key=lambda x: x['page_num'])
    
    output_txt = "OCR_Result.txt"
    with open(output_txt, 'w', encoding='utf-8') as f:
        f.write("# خروجی سیستم OCR فارسی رایگان و نامحدود\n\n")
        for res in all_results:
            f.write(f"\n--- صفحه {res['page_num']} ---\n{res['text_content']}\n")
            
    if os.path.exists(temp_dir): 
        shutil.rmtree(temp_dir)
    if os.path.exists(temp_pdf): 
        os.remove(temp_pdf)
    
    return FileResponse(output_txt, media_type="text/plain", filename="OCR_Result.txt")
