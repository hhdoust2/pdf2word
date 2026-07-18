from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSON_OK, FileResponse
import pytesseract
from PIL import Image, ImageEnhance
from pdf2image import convert_from_path
import os
import shutil
import gc
import time
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# دیکشنری موقت برای ذخیره وضعیت پردازش فایل‌ها
STATUS_DB = {}

def set_paragraph_rtl(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement('w:bidi')
    bidi.set(qn('w:val'), '1')
    pPr.append(bidi)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

def do_ocr_on_one_page(image_file_path, page_number):
    def improve_image_quality(img):
        gray = img.convert('L')
        enhancer = ImageEnhance.Contrast(gray)
        return enhancer.enhance(2.5)

    def make_sharp(img):
        sharpener = ImageEnhance.Sharpness(img)
        return sharpener.enhance(1.3)

    try:
        image = Image.open(image_file_path)
        better_image = improve_image_quality(image)
        final_image = make_sharp(better_image)
        extracted_text = pytesseract.image_to_string(final_image, lang='fas', config='--psm 3 --oem 3')
        
        image.close()
        try: os.remove(image_file_path)
        except: pass
            
        return {'page_num': page_number, 'text_content': extracted_text.strip(), 'character_count': len(extracted_text.strip()), 'is_successful': True}
    except Exception as error:
        try: os.remove(image_file_path)
        except: pass
        return {'page_num': page_number, 'text_content': f"خطا در صفحه {page_number}: {str(error)}", 'character_count': 0, 'is_successful': False}

# این تابع در پس‌زمینه سرور اجرا می‌شود تا کلادفلر منتظر نماند
def background_ocr_task(task_id: str, temp_pdf: str, filename: str):
    output_docx = f"OCR_Result_{task_id}.docx"
    temp_dir = f"/tmp/temp_ocr_{task_id}"
    
    try:
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        pdf_size_mb = os.path.getsize(temp_pdf) / (1024 * 1024)
        image_quality_dpi = 400 if pdf_size_mb < 5 else 350 if pdf_size_mb < 20 else 300
            
        all_ocr_results = []
        page_num = 1
        
        while True:
            images = convert_from_path(temp_pdf, dpi=image_quality_dpi, first_page=page_num, last_page=page_num, fmt='jpeg')
            if not images: break
                    
            full_path = os.path.join(temp_dir, f"page_{page_num:04d}.jpg")
            images[0].save(full_path, 'JPEG', quality=95, optimize=True)
            del images
            gc.collect()
            
            page_result = do_ocr_on_one_page(full_path, page_num)
            all_ocr_results.append(page_result)
            page_num += 1

        all_ocr_results.sort(key=lambda x: x['page_num'])
        
        doc = Document()
        style = doc.styles['Normal']
        style.font.name = 'Arial'
        style.font.size = Pt(13)
        
        total_chars = sum(res['character_count'] for res in all_ocr_results if res['is_successful'])
        successful_count = sum(1 for res in all_ocr_results if res['is_successful'])
        
        p_title = doc.add_paragraph("نتایج سیستم هوشمند OCR فارسی ابری")
        set_paragraph_rtl(p_title)
        p_title.runs[0].font.bold = True
        
        p_meta = doc.add_paragraph(f"فایل مبدا: {filename}\nصفحات موفق: {successful_count} از {len(all_ocr_results)}")
        set_paragraph_rtl(p_meta)
        
        doc.add_paragraph("=" * 60)
        
        for single_result in all_ocr_results:
            p_page = doc.add_paragraph(f"\n--- صفحه {single_result['page_num']} ---")
            set_paragraph_rtl(p_page)
            p_page.runs[0].font.bold = True
            
            p_text = doc.add_paragraph(single_result['text_content'])
            set_paragraph_rtl(p_text)

        doc.save(output_docx)
        STATUS_DB[task_id] = {"status": "completed", "file": output_docx}
        
    except Exception as e:
        STATUS_DB[task_id] = {"status": "failed", "error": str(e)}
    finally:
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        if os.path.exists(temp_pdf): os.remove(temp_pdf)

@app.get("/")
def read_root():
    return {"status": "سرور بهینه‌سازی شده فعال است"}

@app.post("/process-pdf")
async def process_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    task_id = str(int(time.time()))
    temp_pdf = f"input_{task_id}.pdf"
    
    with open(temp_pdf, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    STATUS_DB[task_id] = {"status": "processing"}
    
    # سپردن کار به پس‌زمینه و آزاد کردن فوری کلادفلر
    background_tasks.add_task(background_ocr_task, task_id, temp_pdf, file.filename)
    
    return {"task_id": task_id, "status": "processing"}

@app.get("/get-status/{task_id}")
async def get_status(task_id: str):
    task = STATUS_DB.get(task_id, {"status": "not_found"})
    return task

@app.get("/download/{task_id}")
async def download_file(task_id: str):
    task = STATUS_DB.get(task_id)
    if task and task.get("status") == "completed":
        file_path = task.get("file")
        return FileResponse(file_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename="OCR_Result.docx")
    return {"error": "فایل آماده نیست یا پیدا نشد"}
