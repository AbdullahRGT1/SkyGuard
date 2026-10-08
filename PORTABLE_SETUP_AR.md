# تشغيل SkyGuard بعد النقل لجهاز جديد

هذا الملف يشرح تشغيل المشروع بعد نقله إلى جهاز جديد. الملف المضغوط أو نسخة المشروع لا يجب أن تحتوي على `.venv` لأن مكتبات Python مرتبطة بالجهاز الذي تم تثبيتها عليه.

## المتطلبات

- Windows 10 أو Windows 11.
- Python 3.11 أو أحدث.
- عند تثبيت Python، فعل خيار `Add python.exe to PATH` إن وجد.
- اتصال إنترنت أثناء تثبيت المكتبات.

## التثبيت الأساسي

1. فك ضغط المشروع في مسار واضح، مثل:

   ```powershell
   مسار\المشروع\simple-stream
   ```

2. افتح PowerShell داخل فولدر المشروع.

3. إذا منع Windows تشغيل السكربتات، نفذ هذا الأمر مرة واحدة:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

4. ثبت البيئة والمكتبات الأساسية:

   ```powershell
   .\setup_project.ps1
   ```

5. شغل جهاز الكاميرا/الستريمر:

   ```powershell
   .\.venv\Scripts\python.exe run_streamer.py
   ```

6. شغل جهاز التحكم/الأوبريتور:

   ```powershell
   .\.venv\Scripts\python.exe run_operator.py
   ```

## تفعيل الذكاء الاصطناعي و Smart Alerts

تثبيت AI يتم على جهاز الأوبريتور فقط. الستريمر يرسل الفيديو الخام ولا يحتاج YOLO أو InsightFace.

للأجهزة بدون كارت NVIDIA:

```powershell
.\setup_ai_cpu.ps1
```

للأجهزة التي بها كارت NVIDIA مناسب:

```powershell
.\setup_ai_cuda.ps1
```

السكربتات تثبت:

- PyTorch للـ YOLO.
- `ultralytics` و `cvzone`.
- `insightface` للتعرف على الوجوه.
- `onnxruntime` في نسخة CPU أو `onnxruntime-gpu` في نسخة CUDA.

بعد التثبيت افتح الأوبريتور ثم:

1. افتح `Settings`.
2. من `AI Environment` اضغط `Refresh`.
3. تأكد أن `ultralytics`, `cvzone`, `insightface`, و `onnxruntime` حالتهم `OK`.
4. في CUDA يفضل ظهور `CUDAExecutionProvider` ضمن ONNX providers، وإلا سيعمل InsightFace على CPU.

## Smart Alerts

Smart Alerts لا يلتقط صورًا بنفسه. النظام القديم أو `ViolationCaptureManager` يحفظ صور المخالفات داخل:

```text
Images/
```

بعد حفظ الصورة، Smart Alerts يأخذ مسار الصورة وبيانات YOLO، ثم:

- يستخدم InsightFace لاستخراج الوجوه والـ embeddings.
- يخزن metadata داخل:

  ```text
  face_recognizer/smart_alerts.sqlite3
  ```

- يجمع نفس الشخص داخل نافذة زمنية.
- يرسل أفضل الصور فقط إلى n8n كـ JSON.
- الصور ترسل داخل JSON بصيغة base64 في `images[].data_base64` و `images[].data_url`.

يمكن اختيار موديل InsightFace قبل تشغيل الأوبريتور:

```powershell
$env:SKYGUARD_INSIGHTFACE_MODEL="buffalo_s"
```

استخدم `buffalo_s` للأجهزة الضعيفة، و `buffalo_l` للدقة الأعلى.

## ملاحظات مهمة للشبكة

- لا تكتب `0.0.0.0` في برنامج الأوبريتور.
- استخدم IP جهاز الستريمر على نفس الشبكة، مثل `192.168.1.20`.
- إذا لم يتم الاتصال، اسمح لـ Python أو التطبيق من Windows Defender Firewall.
- الستريمر يحتاج TCP `8765`.
- الأوبريتور يحتاج UDP `5004` لاستقبال الفيديو.

## إعادة تثبيت نظيفة

لو حصلت مشكلة في المكتبات على الجهاز الجديد، نفذ:

```powershell
.\setup_project.ps1 -RecreateVenv
```

ثم ثبت AI مرة أخرى حسب الجهاز:

```powershell
.\setup_ai_cpu.ps1
```

أو:

```powershell
.\setup_ai_cuda.ps1
```
