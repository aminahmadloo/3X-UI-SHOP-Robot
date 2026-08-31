# ToonelVPN custom 3X-UI subscription page

این پوشه قالب اختصاصی فارسی صفحه Subscription برای 3X-UI است.

## مسیر نصب روی سرور

```text
/etc/3x-ui/sub_templates/toonelvpn/
```

فایل اصلی:

```text
index.html
```

در 3X-UI، مسیر **Sub Theme Directory** را روی مسیر بالا قرار دهید.

## نکته مهم

این قالب فقط صفحه HTML اطلاعات اشتراک را عوض می‌کند و به endpointهای اصلی Subscription، JSON یا Clash دست نمی‌زند. برای بازگشت به صفحه پیش‌فرض کافی است مقدار **Sub Theme Directory** را خالی کنید.

قالب از متغیرهای رسمی 3X-UI مانند `subUrl`، `subJsonUrl`، `subClashUrl`، `sId`، `enabled`، `used`، `remained`، `total`، `expire` و `links` استفاده می‌کند.

## تست

بعد از کپی قالب و تنظیم مسیر در 3X-UI، یکی از URLهای Subscription موجود را با مرورگر باز کنید. باید صفحه فارسی ToonelVPN نمایش داده شود. اگر مسیر قالب خالی شود، صفحه پیش‌فرض 3X-UI دوباره قابل استفاده است.
