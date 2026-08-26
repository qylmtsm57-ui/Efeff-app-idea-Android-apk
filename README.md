# FreshStock — Python + Flet

تطبيق إدارة مخزون وصلاحية مبني ببايثون + Flet + SQLite.

## التنبيهات الأصلية في Android

تمت إضافة `flet-android-notifications` لتوفير تنبيهات Android مجدولة عبر AlarmManager:

- ملخص يومي في وقت التنبيه المحدد.
- تنبيه منفصل قبل انتهاء كل منتج بعدد الأيام المحدد.
- دعم Exact Alarm عندما يسمح Android بذلك، مع fallback إلى inexact alarms.
- إعادة جدولة التنبيهات عند إضافة أو تعديل أو حذف المنتجات وعند تغيير إعدادات التنبيه.
- إذن POST_NOTIFICATIONS و SCHEDULE_EXACT_ALARM و RECEIVE_BOOT_COMPLETED.

## التشغيل

```bash
pip install -r requirements.txt
flet run main.py
```

## بناء APK

```bash
flet build apk --python-version 3.13
```

في GitHub Actions استخدم workflow الموجود في `.github/workflows/build-apk.yml`: ينفذ بناءً أوليًا لتوليد قالب Android، ثم يشغل patcher الخاص بالتنبيهات، ثم يعيد بناء APK النهائي.

> الواجهة والمنطق الأساسيان Python + Flet. جزء التنبيهات فقط يستخدم امتدادًا أصليًا للوصول إلى Android AlarmManager/NotificationManager بشكل موثوق.
