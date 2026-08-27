from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingPage:
    title: str
    text: str
    download_url: str | None = None


APP_OVERVIEWS = {
    "happ": (
        "🟢 <b>Happ — آموزش کامل</b>",
        "Happ یک کلاینت چندسکویی مبتنی بر Xray است و برای استفاده از کانفیگ‌ها و لینک‌های اشتراکی ToonelVPN مناسب است.\n\n"
        "در تمام دستگاه‌ها ترتیب کار تقریباً یکسان است: برنامه را نصب کن، لینک/کلید اتصال ToonelVPN را اضافه کن، Subscription را در صورت دریافت لینک اشتراکی وارد کن، سپس یک پروفایل سالم را انتخاب و اتصال را فعال کن.\n\n"
        "⚠️ لینک اشتراک را فقط در اختیار برنامه‌ای قرار بده که به آن اعتماد داری و لینک اختصاصی خودت را با دیگران به اشتراک نگذار."
    ),
    "v2ray": (
        "🔵 <b>V2Ray — آموزش کامل</b>",
        "در این بخش منظور از V2Ray، کلاینت‌های رایج خانواده v2rayN/v2rayNG است که از Xray نیز پشتیبانی می‌کنند.\n\n"
        "برای Windows، Linux و macOS از <b>v2rayN</b> و برای Android از <b>v2rayNG</b> استفاده کن. این کلاینت‌ها برای VLESS، VMess، Trojan و سایر پروتکل‌های سازگار کاربرد دارند.\n\n"
        "⚠️ نسخه‌های رسمی را فقط از مخزن توسعه‌دهنده و صفحه Releases دریافت کن."
    ),
    "v2box": (
        "🟣 <b>V2Box — آموزش کامل</b>",
        "V2Box یک کلاینت V2Ray برای دستگاه‌های Apple است و از پروتکل‌هایی مانند VLESS، VMess، Trojan و Reality پشتیبانی می‌کند.\n\n"
        "برای افزودن سرویس ToonelVPN، لینک یا QR اتصال را طبق امکانات نسخه نصب‌شده وارد کن، پروفایل را انتخاب کن و سپس اتصال را فعال کن.\n\n"
        "⚠️ برای Android در این نسخه لینک رسمی قابل‌اعتماد V2Box تأیید نشده است؛ بنابراین لینک APK ناشناس در ربات قرار نمی‌دهیم."
    ),
}


PAGES: dict[tuple[str, str], TrainingPage] = {
    ("happ", "android"): TrainingPage(
        "🤖 <b>Happ در Android</b>",
        "<b>۱) نصب</b>\nHapp را از Google Play نصب و اجرا کن.\n\n"
        "<b>۲) افزودن سرویس</b>\nلینک اشتراک یا لینک اتصال ToonelVPN را از بخش سرویس‌های من دریافت کن. اگر لینک قابل کلیک است، آن را باز کن تا Happ پیشنهاد شود؛ در غیر این صورت از گزینه افزودن/Import داخل Happ استفاده کن و لینک را Paste کن.\n\n"
        "<b>۳) Subscription</b>\nاگر لینک اشتراک داری، آن را به‌عنوان Subscription اضافه کن تا چند سرور و پروتکل داخل یک پروفایل قرار بگیرند. پس از افزودن، Update/Refresh را اجرا کن.\n\n"
        "<b>۴) اتصال</b>\nیک پروفایل سالم را انتخاب کن، اتصال را Start/Connect کن و اجازه ایجاد VPN را تأیید کن.\n\n"
        "<b>۵) اگر وصل نشد</b>\nابتدا تاریخ و ساعت را روی Automatic بگذار، برنامه را به‌روز کن، Subscription را Refresh کن و یک پروفایل دیگر را امتحان کن. اگر همه پروفایل‌ها خطا دارند، از داخل ربات تیکت پشتیبانی ثبت کن.\n\n"
        "💡 لینک اشتراک شخصی را برای شخص دیگری ارسال نکن؛ ممکن است باعث مصرف ترافیک یا سوءاستفاده از سرویس شود.",
        "https://play.google.com/store/apps/details?id=com.happproxy",
    ),
    ("happ", "ios"): TrainingPage(
        "🍎 <b>Happ در iPhone / iPad</b>",
        "<b>۱) نصب</b>\nHapp را از App Store نصب و اجرا کن.\n\n"
        "<b>۲) افزودن لینک</b>\nلینک اتصال یا Subscription ToonelVPN را از ربات باز کن. در صورت نمایش گزینه Open in Happ آن را انتخاب کن؛ یا لینک را از داخل Happ در بخش افزودن Subscription وارد کن.\n\n"
        "<b>۳) بروزرسانی</b>\nپس از افزودن Subscription، آن را Update کن تا لیست سرورها تازه شود.\n\n"
        "<b>۴) اتصال</b>\nپروفایل موردنظر را انتخاب کن، Connect را بزن و اجازه VPN Configuration را تأیید کن.\n\n"
        "<b>۵) عیب‌یابی</b>\nاگر اتصال برقرار نشد، Happ را کامل ببند و باز کن، Subscription را Refresh کن و یک پروفایل دیگر را امتحان کن. همچنین مطمئن شو iOS به تاریخ و ساعت خودکار تنظیم شده است.\n\n"
        "⚠️ اگر App Store منطقه‌ای اجازه نصب نمی‌دهد، از منابع رسمی و معتبر خود Happ استفاده کن و از APK/IPA ناشناس استفاده نکن.",
        "https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973",
    ),
    ("happ", "windows"): TrainingPage(
        "💻 <b>Happ در Windows</b>",
        "<b>۱) دریافت</b>\nنسخه Windows را فقط از صفحه رسمی Happ در GitHub دریافت کن.\n\n"
        "<b>۲) نصب و اجرا</b>\nفایل نصب را اجرا کن و Happ را باز کن. اگر Windows Defender درباره فایل رسمی هشدار نشان داد، قبل از اجرا نام ناشر و منبع دانلود را بررسی کن.\n\n"
        "<b>۳) افزودن سرویس</b>\nلینک Subscription یا لینک اتصال ToonelVPN را Copy کن و در Happ از بخش افزودن پروفایل/Subscription وارد کن.\n\n"
        "<b>۴) بروزرسانی</b>\nپس از افزودن Subscription، Update/Refresh را بزن تا پروفایل‌ها دریافت شوند.\n\n"
        "<b>۵) اتصال</b>\nپروفایل مناسب را انتخاب و Connect را فعال کن. در اولین اجرا ممکن است Windows برای ایجاد رابط شبکه یا دسترسی لازم درخواست مجوز کند.\n\n"
        "<b>۶) عیب‌یابی</b>\nاگر وصل نشد، Subscription را Refresh کن، پروفایل دیگری را امتحان کن و از خاموش بودن Proxy/VPN دیگری که ممکن است تداخل ایجاد کند مطمئن شو.",
        "https://github.com/happ-proxy",
    ),
    ("happ", "macos"): TrainingPage(
        "🖥 <b>Happ در macOS</b>",
        "Happ نسخه دسکتاپ برای macOS دارد. نسخه مناسب Intel یا Apple Silicon را از منبع رسمی Happ دریافت کن.\n\n"
        "<b>۱.</b> برنامه را نصب و اجرا کن.\n"
        "<b>۲.</b> لینک Subscription/اتصال ToonelVPN را در بخش افزودن پروفایل وارد کن.\n"
        "<b>۳.</b> Subscription را Update کن.\n"
        "<b>۴.</b> پروفایل موردنظر را انتخاب و اتصال را فعال کن.\n\n"
        "اگر macOS اجازه اجرای برنامه را نداد، قبل از هر اقدامی منبع فایل را بررسی کن و فقط نسخه رسمی را استفاده کن.\n\n"
        "در صورت خطای اتصال، Subscription را Refresh و پروفایل دیگری را تست کن.",
        "https://github.com/happ-proxy",
    ),
    ("happ", "linux"): TrainingPage(
        "🐧 <b>Happ در Linux</b>",
        "Happ برای Linux نیز نسخه‌های دسکتاپ ارائه می‌کند. بسته مناسب توزیع و معماری سیستم را از منبع رسمی انتخاب کن.\n\n"
        "<b>۱.</b> نسخه مناسب x64 یا ARM را دریافت و نصب کن.\n"
        "<b>۲.</b> Happ را اجرا کن.\n"
        "<b>۳.</b> Subscription یا لینک اتصال ToonelVPN را اضافه کن.\n"
        "<b>۴.</b> Subscription را Refresh کن.\n"
        "<b>۵.</b> پروفایل سالم را انتخاب و اتصال را فعال کن.\n\n"
        "اگر چند رابط شبکه یا Proxy هم‌زمان فعال هستند، برای تست آن‌ها را غیرفعال کن. سپس یک پروفایل دیگر را امتحان کن.",
        "https://github.com/happ-proxy",
    ),
    ("v2ray", "android"): TrainingPage(
        "🤖 <b>v2rayNG در Android</b>",
        "<b>۱) نصب</b>\nv2rayNG را از GitHub رسمی پروژه دریافت و نصب کن.\n\n"
        "<b>۲) افزودن Subscription</b>\nلینک Subscription ToonelVPN را Copy کن. در v2rayNG از بخش Subscription Group/اشتراک، یک گروه جدید بساز و URL را وارد کن؛ سپس Update را بزن.\n\n"
        "<b>۳) افزودن کانفیگ تکی</b>\nاگر لینک تکی VLESS/VMess/Trojan داری، می‌توانی آن را از طریق Import from Clipboard یا QR وارد کنی.\n\n"
        "<b>۴) اتصال</b>\nپروفایل را انتخاب کن و دکمه اتصال را بزن. مجوز VPN اندروید را در اولین اجرا تأیید کن.\n\n"
        "<b>۵) عیب‌یابی</b>\nSubscription را Update کن، پروفایل دیگری را امتحان کن و در صورت خطای DNS یا شبکه، تنظیمات DNS/Network را بررسی کن.\n\n"
        "⚠️ فقط نسخه رسمی GitHub پروژه را استفاده کن.",
        "https://github.com/2dust/v2rayNG/releases",
    ),
    ("v2ray", "windows"): TrainingPage(
        "💻 <b>v2rayN در Windows</b>",
        "<b>۱) نصب</b>\nآخرین Release رسمی v2rayN را دریافت و استخراج/نصب کن.\n\n"
        "<b>۲) افزودن Subscription</b>\nلینک Subscription ToonelVPN را Copy کن. در v2rayN از منوی Subscription Group آن را اضافه و سپس Update subscriptions را اجرا کن.\n\n"
        "<b>۳) کانفیگ تکی</b>\nبرای لینک VLESS/VMess/Trojan می‌توانی از Import from Clipboard یا QR استفاده کنی.\n\n"
        "<b>۴) انتخاب و اتصال</b>\nپروفایل را انتخاب کن، سپس Set as active server و گزینه Proxy/System Proxy موردنیاز را فعال کن.\n\n"
        "<b>۵) تست</b>\nابتدا یک پروفایل دیگر را امتحان کن و مطمئن شو Proxy یا VPN دیگری هم‌زمان فعال نیست.\n\n"
        "💡 نسخه‌های جدید v2rayN از Xray و چند هسته دیگر پشتیبانی می‌کنند؛ بنابراین گزینه‌های رابط ممکن است با نسخه‌های قدیمی کمی متفاوت باشند.",
        "https://github.com/2dust/v2rayN/releases",
    ),
    ("v2ray", "macos"): TrainingPage(
        "🖥 <b>v2rayN در macOS</b>",
        "v2rayN برای macOS نیز نسخه رسمی دارد.\n\n"
        "<b>۱.</b> نسخه مناسب Intel یا Apple Silicon را از Releases دریافت کن.\n"
        "<b>۲.</b> برنامه را اجرا کن و در صورت درخواست macOS مجوز لازم را تأیید کن.\n"
        "<b>۳.</b> لینک Subscription ToonelVPN را در Subscription Group اضافه کن و Update بزن.\n"
        "<b>۴.</b> یک سرور را انتخاب و فعال کن.\n"
        "<b>۵.</b> برای اعمال پروکسی روی سیستم، System Proxy را مطابق نیاز فعال کن.\n\n"
        "در صورت مشکل، یک سرور دیگر را تست کن و Proxy/VPNهای هم‌زمان را خاموش کن.",
        "https://github.com/2dust/v2rayN/releases",
    ),
    ("v2ray", "linux"): TrainingPage(
        "🐧 <b>v2rayN در Linux</b>",
        "v2rayN نسخه‌هایی برای Linux ارائه می‌کند.\n\n"
        "<b>۱.</b> بسته مناسب معماری سیستم را از Releases رسمی دریافت کن.\n"
        "<b>۲.</b> برنامه را نصب و اجرا کن.\n"
        "<b>۳.</b> Subscription ToonelVPN را در بخش Subscription Group وارد و Update کن.\n"
        "<b>۴.</b> پروفایل موردنظر را فعال کن.\n"
        "<b>۵.</b> Proxy سیستم را طبق محیط دسکتاپ/تنظیمات شبکه فعال کن.\n\n"
        "اگر برنامه اجرا شد ولی اینترنت عبور نکرد، وضعیت System Proxy و DNS را بررسی کن و یک پروفایل دیگر را تست کن.",
        "https://github.com/2dust/v2rayN/releases",
    ),
    ("v2box", "ios"): TrainingPage(
        "🍎 <b>V2Box در iPhone / iPad</b>",
        "<b>۱) نصب</b>\nV2Box را از App Store نصب و اجرا کن.\n\n"
        "<b>۲) افزودن سرویس</b>\nدر V2Box به بخش Configs برو. بسته به نسخه برنامه می‌توانی لینک/کانفیگ را از Clipboard وارد کنی یا از QR استفاده کنی.\n\n"
        "<b>۳) Subscription</b>\nاگر لینک اشتراک ToonelVPN داری، آن را در بخش مربوط به Subscription/Import وارد و Update کن.\n\n"
        "<b>۴) اتصال</b>\nپروفایل موردنظر را انتخاب کن و Connect را بزن. مجوز ایجاد VPN را در iOS تأیید کن.\n\n"
        "<b>۵) عیب‌یابی</b>\nاگر اتصال برقرار نشد، Subscription را Refresh کن، پروفایل دیگری را امتحان کن و مطمئن شو VPN دیگری هم‌زمان فعال نیست.\n\n"
        "⚠️ لینک رسمی قابل‌اعتماد V2Box برای iPhone/iPad همین App Store است.",
        "https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690",
    ),
    ("v2box", "macos"): TrainingPage(
        "🖥 <b>V2Box در macOS</b>",
        "V2Box برای Mac نیز از طریق App Store ارائه شده است.\n\n"
        "<b>۱.</b> برنامه را از App Store نصب کن.\n"
        "<b>۲.</b> V2Box را باز کن.\n"
        "<b>۳.</b> کانفیگ یا Subscription ToonelVPN را از Clipboard/QR یا بخش Import اضافه کن.\n"
        "<b>۴.</b> پروفایل را انتخاب و اتصال را فعال کن.\n\n"
        "اگر اتصال برقرار نشد، Subscription را Update کن و پروفایل دیگری را امتحان کن.\n\n"
        "⚠️ برای V2Box در macOS نیز فقط منبع رسمی App Store توصیه می‌شود.",
        "https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690",
    ),
}
