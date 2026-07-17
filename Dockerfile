FROM python:3.10-slim

# آپدیت سیستم‌عامل لینوکس سرور و نصب تسرکت فارسی و پوپلر پی‌دی‌اف
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-fas \
    poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# اکسپوز پورت ۱۰۰۰۰ که استاندارد رندر برای وب‌سرویس‌هاست
EXPOSE 10000

# اجرای سرور وب با وب‌سرور uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
