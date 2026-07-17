from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import pytesseract
from PIL import Image, ImageEnhance
from pdf2image import convert_from_path
import os
import shutil
import gc

app = FastAPI()

# تنظیمات کاملاً باز و اصلاح‌شده بدون تداخل برای مرورگرها
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # تغییر به False برای جلوگیری از مسدودی لایه امنیتی مرورگر
    allow_methods=["*"],
    allow_headers=["*"],
)

def process_single_page_ocr(img_path, page_num):
    try:
        with Image.open(img_path) as image:
            gray = image.convert('L')
            enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
            final_image = ImageEnhance.Sharpness(enhanced).enhance(1.2)
            extracted_text = pytesseract.image_to_string(final_image, lang='fas', config='--psm 3 --oem 3')
        try: os.remove(img_path)
        except: pass
        return f"\n--- صفحه {page_num} ---\n{extracted_text.strip()}\n"
    except Exception as e:
        return f"\n--- صفحه {page_num} (خطا) ---\n{str(e)}\n"

@app.get("/")
def read_root():
    return {"status": "سرور فعال است"}

@app.post("/process-pdf")
async def process_pdf(file: UploadFile = File(...)):
    temp_pdf = "input.pdf"
    output_txt = "OCR_Result.txt"
    temp_dir = "./temp_images"
    
    with open(temp_pdf, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    with open(output_txt, 'w', encoding='utf-8') as out_file:
        out_file.write("# خروجی سیستم OCR فارسی رایگان و نامحدود\n\n")
        page_num = 1
        while True:
            try:
                images = convert_from_path(temp_pdf, dpi=150, first_page=page_num, last_page=page_num, fmt='jpeg')
                if not images:
                    break
                path = os.path.join(temp_dir, f"page_{page_num:04d}.jpg")
                images[0].save(path, 'JPEG', quality=80)
                del images
                gc.collect()
                
                page_text = process_single_page_ocr(path, page_num)
                out_file.write(page_text)
                page_num += 1
            except:
                break

    if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
    if os.path.exists(temp_pdf): os.remove(temp_pdf)
    
    return FileResponse(output_txt, media_type="text/plain", filename="OCR_Result.txt")
