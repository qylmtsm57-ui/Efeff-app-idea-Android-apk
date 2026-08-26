import asyncio
import re
from datetime import datetime, date, timedelta, time
import flet as ft
from database import Database, expiry_status, days_left

try:
    from flet_android_notifications import FletAndroidNotifications
except Exception:
    FletAndroidNotifications = None

APP_NAME = "FreshStock"
APP_VERSION = "1.1.0"
BG, CARD, TEXT, MUTED = "#F6F7FB", "#FFFFFF", "#18212F", "#737D8C"
PRIMARY, BORDER = "#315BEA", "#E4E8F0"
GREEN, RED, ORANGE, PURPLE = "#16A57A", "#E4515A", "#F29A27", "#7657D9"
BLUE_LIGHT, RED_LIGHT = "#EAF0FF", "#FFF0F1"
ORANGE_LIGHT, GREEN_LIGHT, PURPLE_LIGHT = "#FFF5E7", "#E9F8F3", "#F1EDFF"


def num(v, default=0.0):
    try:
        s = str(v or "").strip().replace(",", ".")
        return float(s) if s else default
    except (ValueError, TypeError):
        return default


def fmt(v):
    n = num(v)
    return str(int(n)) if n.is_integer() else f"{n:,.2f}".rstrip("0").rstrip(".")


def money(v):
    return f"{num(v):,.2f}"


def parse_date(v):
    if not v:
        return None
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(v).strip(), f).date()
        except ValueError:
            pass
    return None


def normalize_date(v):
    d = parse_date(v)
    return d.isoformat() if d else str(v or "").strip()


def status_meta(p, soon):
    st = expiry_status(p.get("expiry_date", ""), soon)
    if st == "expired":
        d = days_left(p.get("expiry_date", ""))
        return ("منتهي" if d is None else ("منتهي اليوم" if d == 0 else f"منتهي منذ {abs(d)} يوم"), RED, RED_LIGHT, ft.Icons.ERROR_OUTLINE)
    if st == "soon":
        d = days_left(p.get("expiry_date", ""))
        return ("ينتهي اليوم" if d == 0 else ("متبقي يوم" if d == 1 else f"متبقي {d} يوم"), ORANGE, ORANGE_LIGHT, ft.Icons.WARNING_AMBER_OUTLINED)
    if st == "safe":
        return "سليم", GREEN, GREEN_LIGHT, ft.Icons.CHECK_CIRCLE_OUTLINE
    return "بدون تاريخ", MUTED, "#EFF1F5", ft.Icons.HELP_OUTLINE


class FreshStock:
    def __init__(self, page):
        self.page = page
        self.db = Database()
        self.index = 0
        self.search_text = ""
        self.inventory_filter = "all"
        self.file_picker = ft.FilePicker()
        page.overlay.append(self.file_picker)
        self.notifications = None
        self._syncing = False
        if FletAndroidNotifications:
            try:
                self.notifications = FletAndroidNotifications(on_notification_tap=self.on_notification_tap)
            except Exception as e:
                print(f"Notifications unavailable: {e}")

    def setup(self):
        p = self.page
        p.title = APP_NAME
        p.padding = 0
        p.spacing = 0
        p.bgcolor = BG
        p.theme = ft.Theme(font_family="Arial")
        p.theme_mode = ft.ThemeMode.DARK if self.db.get_setting("dark_mode", "0") == "1" else ft.ThemeMode.LIGHT
        try:
            p.window.width, p.window.height = 390, 844
            p.set_allowed_device_orientations([ft.DeviceOrientation.PORTRAIT_UP, ft.DeviceOrientation.PORTRAIT_DOWN])
        except Exception:
            pass
        if self.db.onboarding_done():
            self.render()
        else:
            self.onboarding()
        try:
            p.run_task(self.sync_notifications)
        except Exception:
            pass

    def on_notification_tap(self, e):
        self.index = 2
        self.render()

    def render(self):
        self.page.clean()
        builders = [self.home, self.inventory, self.alerts, self.settings]
        self.index = max(0, min(self.index, 3))
        self.page.add(ft.SafeArea(expand=True, content=ft.Column(expand=True, spacing=0, controls=[builders[self.index](), self.nav()])))
        self.page.update()

    def nav(self):
        return ft.NavigationBar(
            selected_index=self.index, height=72, bgcolor=CARD, indicator_color=BLUE_LIGHT,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.HOME_OUTLINED, selected_icon=ft.Icons.HOME, label="الرئيسية"),
                ft.NavigationBarDestination(icon=ft.Icons.INVENTORY_2_OUTLINED, selected_icon=ft.Icons.INVENTORY_2, label="المخزون"),
                ft.NavigationBarDestination(icon=ft.Icons.NOTIFICATIONS_NONE, selected_icon=ft.Icons.NOTIFICATIONS, label="التنبيهات"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="الإعدادات"),
            ], on_change=lambda e: (setattr(self, "index", e.control.selected_index), self.render())
        )

    def onboarding(self):
        def finish(e):
            self.db.set_onboarding_done(True)
            self.render()
        self.page.clean()
        self.page.add(ft.Container(expand=True, bgcolor=BG, padding=22, content=ft.Column(expand=True, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, controls=[
            ft.Container(width=82, height=82, border_radius=24, bgcolor=PRIMARY, alignment=ft.Alignment(0,0), content=ft.Icon(ft.Icons.INVENTORY_2, color="white", size=42)),
            ft.Text(APP_NAME, size=28, weight=ft.FontWeight.BOLD, color=TEXT),
            ft.Text("إدارة المخزون وتواريخ الصلاحية بسهولة", size=14, color=MUTED, text_align=ft.TextAlign.CENTER),
            ft.Container(height=10),
            ft.FilledButton("الدخول محلياً", icon=ft.Icons.PERSON_OUTLINE, width=330, height=50, on_click=finish, style=ft.ButtonStyle(bgcolor=PRIMARY, color="white", shape=ft.RoundedRectangleBorder(radius=14))),
            ft.Text("لا تحتاج إلى حساب أو اتصال بالإنترنت", size=11, color=MUTED),
        ])))
        self.page.update()

    def header(self, title, subtitle="", action=None):
        return ft.Container(padding=ft.padding.only(left=14,right=14,top=8,bottom=8), content=ft.Row(rtl=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
            action or ft.Container(width=42,height=42,border_radius=14,bgcolor=PRIMARY,alignment=ft.Alignment(0,0),content=ft.Icon(ft.Icons.INVENTORY_2_OUTLINED,color="white")),
            ft.Container(expand=True,padding=ft.padding.symmetric(horizontal=8),content=ft.Column(spacing=2,horizontal_alignment=ft.CrossAxisAlignment.END,controls=[ft.Text(title,size=20,weight=ft.FontWeight.BOLD,color=TEXT)] + ([ft.Text(subtitle,size=11,color=MUTED)] if subtitle else []))),
            ft.IconButton(icon=ft.Icons.NOTIFICATIONS_NONE,icon_color=TEXT,on_click=lambda _: self.goto(2)),
        ]))

    def goto(self, i):
        self.index = i
        self.render()

    def empty(self, icon, title, subtitle):
        return ft.Container(padding=30, alignment=ft.Alignment(0,0), content=ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER,spacing=8,controls=[ft.Container(width=68,height=68,border_radius=34,bgcolor=BLUE_LIGHT,alignment=ft.Alignment(0,0),content=ft.Icon(icon,color=PRIMARY,size=32)),ft.Text(title,size=15,weight=ft.FontWeight.BOLD,color=TEXT,text_align=ft.TextAlign.CENTER),ft.Text(subtitle,size=12,color=MUTED,text_align=ft.TextAlign.CENTER)]))

    def stat(self, title, value, icon, bg):
        return ft.Container(expand=True,padding=12,bgcolor=CARD,border_radius=16,border=ft.border.all(1,BORDER),content=ft.Row(rtl=True,alignment=ft.MainAxisAlignment.SPACE_BETWEEN,controls=[ft.Column(spacing=1,horizontal_alignment=ft.CrossAxisAlignment.END,controls=[ft.Text(title,size=11,color=MUTED),ft.Text(str(value),size=22,weight=ft.FontWeight.BOLD,color=TEXT)]),ft.Container(width=40,height=40,border_radius=12,bgcolor=bg,alignment=ft.Alignment(0,0),content=ft.Icon(icon,color="white",size=20))]))

    def priority_key(self, p):
        d = parse_date(p.get("expiry_date"))
        left = (d-date.today()).days if d else 999999
        q, m = num(p.get("quantity")), num(p.get("minimum_quantity"))
        low = m > 0 and q <= m
        return (0 if left < 0 else 1 if left <= 7 else 2, left, 0 if low else 1, (p.get("name") or "").lower())

    def home(self):
        c = self.db.counts()
        products = self.db.all_products()
        soon = int(num(self.db.get_setting("expiry_days","7"),7))
        priority = [p for p in products if expiry_status(p.get("expiry_date",""),soon) in ("expired","soon") or (num(p.get("minimum_quantity")) > 0 and num(p.get("quantity")) <= num(p.get("minimum_quantity")))]
        priority.sort(key=self.priority_key)
        search = ft.TextField(hint_text="ابحث عن منتج أو باركود...",prefix_icon=ft.Icons.SEARCH,height=48,border_radius=14,bgcolor=CARD,border_color=BORDER,text_align=ft.TextAlign.RIGHT,on_change=self.home_search,on_submit=self.home_submit)
        body = ft.Column(spacing=8,controls=[self.card(p,True) for p in priority[:5]]) if priority else self.empty(ft.Icons.INVENTORY_2_OUTLINED,"لا توجد منتجات تحتاج إلى إجراء","أضف المنتجات وسيتم حساب الصلاحية والمخزون تلقائياً")
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,controls=[self.header(APP_NAME,"إدارة المخزون والصلاحية"),ft.Container(padding=ft.padding.symmetric(horizontal=16),content=search),ft.Container(padding=ft.padding.only(left=16,right=16,top=12),content=ft.Container(padding=14,bgcolor="#FFF4DE",border_radius=16,border=ft.border.all(1,"#F4D99D"),content=ft.Row(rtl=True,controls=[ft.Icon(ft.Icons.LIGHTBULB_OUTLINED,color=ORANGE),ft.Column(expand=True,spacing=2,horizontal_alignment=ft.CrossAxisAlignment.END,controls=[ft.Text("نظام الصلاحية الذكي",weight=ft.FontWeight.BOLD,color=TEXT),ft.Text("يعرض المنتجات حسب أولوية انتهاء الصلاحية FEFO",size=11,color=MUTED)])]))),ft.Container(padding=16,content=ft.Column(spacing=9,controls=[ft.Row(spacing=9,controls=[self.stat("المنتجات",c["total"],ft.Icons.INVENTORY_2_OUTLINED,PRIMARY),self.stat("منتهية",c["expired"],ft.Icons.ERROR_OUTLINE,RED)]),ft.Row(spacing=9,controls=[self.stat("قريبة الانتهاء",c["soon"],ft.Icons.WARNING_AMBER_OUTLINED,ORANGE),self.stat("مخزون منخفض",c["low"],ft.Icons.TRENDING_DOWN,PURPLE)])])),ft.Container(padding=ft.padding.only(left=16,right=16,bottom=8),content=ft.Row(rtl=True,alignment=ft.MainAxisAlignment.SPACE_BETWEEN,controls=[ft.Text("الأولوية الآن",size=17,weight=ft.FontWeight.BOLD,color=TEXT),ft.TextButton("عرض الكل",on_click=lambda _: self.goto(1))])),ft.Container(padding=ft.padding.symmetric(horizontal=16),content=body),ft.Container(height=14)])

    def home_search(self,e):
        self.search_text = e.control.value or ""
        if self.search_text.strip(): self.index = 1
        self.render()

    def home_submit(self,e):
        self.search_text = e.control.value or ""
        self.index = 1
        self.render()

    def card(self,p,compact=False):
        soon=int(num(self.db.get_setting("expiry_days","7"),7))
        label,color,bg,icon=status_meta(p,soon)
        q,m= num(p.get("quantity")),num(p.get("minimum_quantity"))
        if m>0 and q<=m and expiry_status(p.get("expiry_date",""),soon)=="safe":
            label,color,bg,icon="مخزون منخفض",PURPLE,PURPLE_LIGHT,ft.Icons.TRENDING_DOWN
        controls=[ft.Text(p.get("name") or "بدون اسم",size=14,weight=ft.FontWeight.BOLD,color=TEXT,max_lines=1,overflow=ft.TextOverflow.ELLIPSIS),ft.Text(f"الكمية: {fmt(q)} {p.get('unit') or 'قطعة'}",size=11,color=MUTED),ft.Text(f"الانتهاء: {p.get('expiry_date') or 'غير محدد'}",size=11,color=MUTED)]
        if p.get("barcode") and not compact: controls.append(ft.Text(f"باركود: {p['barcode']}",size=10,color=MUTED))
        return ft.Container(padding=12,bgcolor=CARD,border_radius=15,border=ft.border.all(1,BORDER),on_click=lambda _: self.details(p["id"]),content=ft.Row(rtl=True,spacing=10,controls=[ft.Container(width=42,height=42,border_radius=13,bgcolor=bg,alignment=ft.Alignment(0,0),content=ft.Icon(icon,color=color,size=21)),ft.Column(expand=True,spacing=2,horizontal_alignment=ft.CrossAxisAlignment.END,controls=controls),ft.Container(padding=ft.padding.symmetric(horizontal=8,vertical=5),bgcolor=bg,border_radius=10,content=ft.Text(label,size=10,weight=ft.FontWeight.BOLD,color=color))]))

    def inventory(self):
        products=self.db.all_products(); q=self.search_text.strip().lower()
        if q: products=[p for p in products if q in (p.get("name") or "").lower() or q in (p.get("barcode") or "").lower() or q in (p.get("category") or "").lower()]
        days=int(num(self.db.get_setting("expiry_days","7"),7))
        if self.inventory_filter=="expired": products=[p for p in products if expiry_status(p.get("expiry_date",""),days)=="expired"]
        elif self.inventory_filter=="soon": products=[p for p in products if expiry_status(p.get("expiry_date",""),days)=="soon"]
        elif self.inventory_filter=="low": products=[p for p in products if num(p.get("minimum_quantity"))>0 and num(p.get("quantity"))<=num(p.get("minimum_quantity"))]
        elif self.inventory_filter=="safe": products=[p for p in products if expiry_status(p.get("expiry_date",""),days)=="safe"]
        products.sort(key=self.priority_key)
        search=ft.TextField(value=self.search_text,hint_text="بحث بالاسم أو الباركود أو التصنيف",prefix_icon=ft.Icons.SEARCH,height=48,border_radius=14,bgcolor=CARD,border_color=BORDER,text_align=ft.TextAlign.RIGHT,on_change=self.inventory_search)
        chips=ft.Row(scroll=ft.ScrollMode.AUTO,spacing=7,controls=[self.chip("الكل","all"),self.chip("قريب الانتهاء","soon"),self.chip("منتهي","expired"),self.chip("منخفض","low"),self.chip("سليم","safe")])
        body=ft.Column(spacing=8,controls=[self.card(p) for p in products]) if products else self.empty(ft.Icons.SEARCH_OFF,"لا توجد نتائج","جرّب تغيير البحث أو الفلتر")
        fab=ft.FloatingActionButton(icon=ft.Icons.ADD,mini=True,bgcolor=PRIMARY,foreground_color="white",on_click=lambda _: self.form())
        return ft.Column(expand=True,controls=[self.header("المخزون",f"{len(products)} منتج",ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE,icon_color=PRIMARY,on_click=lambda _: self.form())),ft.Container(padding=ft.padding.symmetric(horizontal=16),content=search),ft.Container(padding=ft.padding.only(left=16,right=16,top=10,bottom=7),content=chips),ft.Container(expand=True,padding=ft.padding.symmetric(horizontal=16),content=ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,controls=[body])),ft.Container(padding=10,alignment=ft.Alignment(1,0),content=fab)])

    def chip(self,label,value):
        active=self.inventory_filter==value
        return ft.Container(padding=ft.padding.symmetric(horizontal=13,vertical=8),border_radius=18,bgcolor=PRIMARY if active else CARD,border=ft.border.all(1,PRIMARY if active else BORDER),on_click=lambda _: self.set_filter(value),content=ft.Text(label,size=11,weight=ft.FontWeight.BOLD,color="white" if active else MUTED))

    def set_filter(self,v): self.inventory_filter=v; self.render()
    def inventory_search(self,e): self.search_text=e.control.value or ""; self.render()

    def form(self, product=None):
        editing=product is not None
        if isinstance(product,int): product=self.db.get_product(product)
        product=product or {}; fields={}
        def field(k,label,icon,keyboard=None,default=""):
            fields[k]=ft.TextField(label=label,value=str(product.get(k,default) or ""),prefix_icon=icon,text_align=ft.TextAlign.RIGHT,border_radius=12,border_color=BORDER,bgcolor=CARD,keyboard_type=keyboard)
            return fields[k]
        content=ft.Column(scroll=ft.ScrollMode.AUTO,spacing=10,controls=[field("name","اسم المنتج *",ft.Icons.LABEL_OUTLINE),ft.Row(spacing=8,controls=[field("quantity","الكمية",ft.Icons.NUMB_1,ft.KeyboardType.NUMBER),field("unit","الوحدة",ft.Icons.STRAIGHTEN,default="قطعة")]),ft.Row(spacing=8,controls=[field("category","التصنيف",ft.Icons.CATEGORY_OUTLINED),field("barcode","الباركود",ft.Icons.QR_CODE_SCANNER)]),ft.Row(spacing=8,controls=[field("production_date","تاريخ الإنتاج",ft.Icons.CALENDAR_MONTH),field("expiry_date","تاريخ الانتهاء",ft.Icons.EVENT_BUSY)]),ft.Row(spacing=8,controls=[field("minimum_quantity","الحد الأدنى",ft.Icons.WARNING_AMBER_OUTLINED,ft.KeyboardType.NUMBER),field("price","السعر",ft.Icons.PAYMENTS_OUTLINED,ft.KeyboardType.NUMBER)]),field("notes","ملاحظات",ft.Icons.NOTES_OUTLINED),ft.Text("التاريخ: YYYY-MM-DD أو DD/MM/YYYY",size=10,color=MUTED)])
        def save(e):
            name=(fields["name"].value or "").strip()
            if not name: fields["name"].error_text="اسم المنتج مطلوب"; fields["name"].update(); return
            prod, exp=(fields["production_date"].value or "").strip(),(fields["expiry_date"].value or "").strip()
            if prod and not parse_date(prod): fields["production_date"].error_text="صيغة التاريخ غير صحيحة"; fields["production_date"].update(); return
            if exp and not parse_date(exp): fields["expiry_date"].error_text="صيغة التاريخ غير صحيحة"; fields["expiry_date"].update(); return
            if prod and exp and parse_date(exp)<parse_date(prod): fields["expiry_date"].error_text="تاريخ الانتهاء قبل تاريخ الإنتاج"; fields["expiry_date"].update(); return
            data={k:(fields[k].value or "").strip() for k in fields}
            data["production_date"]=normalize_date(data["production_date"]); data["expiry_date"]=normalize_date(data["expiry_date"])
            data["quantity"]=num(data["quantity"]); data["minimum_quantity"]=num(data["minimum_quantity"]); data["price"]=num(data["price"]); data["unit"]=data["unit"] or "قطعة"
            if editing: self.db.update_product(product["id"],data); msg="تم تعديل المنتج بنجاح"
            else: self.db.add_product(data); msg="تمت إضافة المنتج بنجاح"
            self.close(); self.render(); self.toast(msg)
            try: self.page.run_task(self.sync_notifications)
            except Exception: pass
        self.show(ft.AlertDialog(modal=True,title=ft.Text("تعديل المنتج" if editing else "إضافة منتج",weight=ft.FontWeight.BOLD),content=ft.Container(width=390,height=500,content=content),actions=[ft.TextButton("إلغاء",on_click=lambda _: self.close()),ft.FilledButton("حفظ",icon=ft.Icons.SAVE,on_click=save,style=ft.ButtonStyle(bgcolor=PRIMARY,color="white"))],actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

    def details(self,pid):
        p=self.db.get_product(pid)
        if not p: self.toast("المنتج غير موجود"); return
        label,color,bg,icon=status_meta(p,int(num(self.db.get_setting("expiry_days","7"),7)))
        content=ft.Column(scroll=ft.ScrollMode.AUTO,spacing=2,controls=[ft.Container(padding=12,bgcolor=bg,border_radius=14,content=ft.Row(rtl=True,controls=[ft.Icon(icon,color=color),ft.Text(label,weight=ft.FontWeight.BOLD,color=color)])),self.info("الباركود",p.get("barcode") or "—"),self.info("الكمية",f"{fmt(p.get('quantity'))} {p.get('unit') or 'قطعة'}"),self.info("التصنيف",p.get("category") or "—"),self.info("تاريخ الإنتاج",p.get("production_date") or "—"),self.info("تاريخ الانتهاء",p.get("expiry_date") or "—"),self.info("السعر",money(p.get("price"))),self.info("الحد الأدنى",fmt(p.get("minimum_quantity"))),self.info("الملاحظات",p.get("notes") or "—")])
        def edit(e): self.close(); self.form(p)
        def delete(e): self.close(); self.confirm_delete(p)
        self.show(ft.AlertDialog(modal=True,title=ft.Text(p.get("name") or "المنتج",weight=ft.FontWeight.BOLD),content=ft.Container(width=390,height=430,content=content),actions=[ft.TextButton("حذف",icon=ft.Icons.DELETE_OUTLINE,on_click=delete,style=ft.ButtonStyle(color=RED)),ft.FilledButton("تعديل",icon=ft.Icons.EDIT,on_click=edit,style=ft.ButtonStyle(bgcolor=PRIMARY,color="white"))],actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

    def info(self,k,v):
        return ft.Container(padding=ft.padding.symmetric(vertical=7),border=ft.border.only(bottom=ft.BorderSide(1,BORDER)),content=ft.Row(rtl=True,controls=[ft.Text(k,size=11,color=MUTED),ft.Text(str(v),size=12,color=TEXT,expand=True,text_align=ft.TextAlign.LEFT)]))

    def confirm_delete(self,p):
        def yes(e):
            self.db.delete_product(p["id"]); self.close(); self.render(); self.toast("تم حذف المنتج")
            try: self.page.run_task(self.sync_notifications)
            except Exception: pass
        self.show(ft.AlertDialog(modal=True,title=ft.Text("حذف المنتج",weight=ft.FontWeight.BOLD),content=ft.Text(f"هل تريد حذف «{p.get('name','المنتج')}» نهائياً؟"),actions=[ft.TextButton("إلغاء",on_click=lambda _: self.close()),ft.TextButton("حذف",on_click=yes,style=ft.ButtonStyle(color=RED))]))

    def alerts(self):
        days=int(num(self.db.get_setting("expiry_days","7"),7)); items=[]
        for p in self.db.all_products():
            st=expiry_status(p.get("expiry_date",""),days); low=num(p.get("minimum_quantity"))>0 and num(p.get("quantity"))<=num(p.get("minimum_quantity"))
            if st in ("expired","soon") or low: items.append((p,st))
        items.sort(key=lambda x:self.priority_key(x[0]))
        if not items: body=self.empty(ft.Icons.NOTIFICATIONS_OFF_OUTLINED,"لا توجد تنبيهات","كل شيء تحت السيطرة حالياً")
        else:
            cards=[]
            for p,st in items:
                if st=="expired": title,color,bg="منتج منتهي",RED,RED_LIGHT
                elif st=="soon": title,color,bg="منتج قريب من الانتهاء",ORANGE,ORANGE_LIGHT
                else: title,color,bg="مخزون منخفض",PURPLE,PURPLE_LIGHT
                cards.append(ft.Container(padding=12,bgcolor=CARD,border_radius=15,border=ft.border.all(1,BORDER),on_click=lambda _,pid=p["id"]: self.details(pid),content=ft.Row(rtl=True,spacing=10,controls=[ft.Container(width=40,height=40,border_radius=12,bgcolor=bg,alignment=ft.Alignment(0,0),content=ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE,color=color)),ft.Column(expand=True,spacing=2,horizontal_alignment=ft.CrossAxisAlignment.END,controls=[ft.Text(title,size=13,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text(p.get("name", ""),size=12,color=MUTED),ft.Text(f"الانتهاء: {p.get('expiry_date') or '—'} • الكمية: {fmt(p.get('quantity'))}",size=10,color=MUTED)])])))
            body=ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,spacing=8,controls=cards)
        return ft.Column(expand=True,controls=[self.header("التنبيهات",f"{len(items)} تنبيه"),ft.Container(expand=True,padding=16,content=body)])

    def settings(self):
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,controls=[self.header("الإعدادات","التخصيص والبيانات والتنبيهات"),ft.Container(padding=16,content=ft.Column(spacing=10,controls=[ft.Text("التنبيهات",size=13,weight=ft.FontWeight.BOLD,color=PRIMARY),self.switch("تشغيل التنبيهات","notifications",ft.Icons.NOTIFICATIONS_OUTLINED),self.switch("تنبيه انخفاض المخزون","low_stock",ft.Icons.INVENTORY_2_OUTLINED),self.switch("تنبيه قرب انتهاء الصلاحية","expiry_alerts",ft.Icons.EVENT_OUTLINED),self.action("وقت التنبيه اليومي",self.db.get_setting("alert_time","09:00"),ft.Icons.ACCESS_TIME,self.edit_time),self.action("أيام التنبيه قبل الانتهاء",f"{self.db.get_setting('expiry_days','7')} أيام",ft.Icons.DATE_RANGE,self.edit_days),ft.Text("البيانات",size=13,weight=ft.FontWeight.BOLD,color=PRIMARY),self.action("تصدير CSV","حفظ قائمة المنتجات",ft.Icons.DOWNLOAD,self.export_csv),self.action("نسخة احتياطية JSON","حفظ المنتجات والإعدادات",ft.Icons.BACKUP_OUTLINED,self.backup),self.action("استعادة نسخة","استيراد ملف JSON",ft.Icons.RESTORE,self.restore),ft.Text("المظهر",size=13,weight=ft.FontWeight.BOLD,color=PRIMARY),self.switch("الوضع الداكن","dark_mode",ft.Icons.DARK_MODE_OUTLINED),self.action("حول التطبيق",f"{APP_NAME} {APP_VERSION}",ft.Icons.INFO_OUTLINE,self.about),ft.Container(height=14),ft.Text("Python + Flet + SQLite • يعمل محلياً",size=10,color=MUTED,text_align=ft.TextAlign.CENTER)]))])

    def switch(self,title,key,icon):
        value=self.db.get_setting(key,"0")=="1"
        return ft.Container(padding=12,bgcolor=CARD,border_radius=14,border=ft.border.all(1,BORDER),content=ft.Row(rtl=True,controls=[ft.Icon(icon,color=MUTED),ft.Column(expand=True,spacing=2,horizontal_alignment=ft.CrossAxisAlignment.END,controls=[ft.Text(title,size=13,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text("مفعّل" if value else "متوقف",size=10,color=MUTED)]),ft.Switch(value=value,on_change=lambda e,k=key:self.toggle(k,e.control.value))]))

    def action(self,title,subtitle,icon,callback):
        return ft.Container(padding=12,bgcolor=CARD,border_radius=14,border=ft.border.all(1,BORDER),on_click=callback,content=ft.Row(rtl=True,controls=[ft.Icon(ft.Icons.CHEVRON_LEFT,color=MUTED),ft.Column(expand=True,spacing=2,horizontal_alignment=ft.CrossAxisAlignment.END,controls=[ft.Text(title,size=13,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text(subtitle,size=10,color=MUTED)]),ft.Container(width=38,height=38,border_radius=11,bgcolor=BLUE_LIGHT,alignment=ft.Alignment(0,0),content=ft.Icon(icon,color=PRIMARY,size=20))]))

    def toggle(self,key,value):
        self.db.set_setting(key,"1" if value else "0")
        if key=="dark_mode": self.page.theme_mode=ft.ThemeMode.DARK if value else ft.ThemeMode.LIGHT
        self.render()
        try: self.page.run_task(self.sync_notifications)
        except Exception: pass

    def edit_time(self,e=None):
        f=ft.TextField(label="الوقت",value=self.db.get_setting("alert_time","09:00"),hint_text="HH:MM",text_align=ft.TextAlign.CENTER)
        def save(e):
            v=(f.value or "").strip()
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",v): f.error_text="أدخل الوقت بصيغة HH:MM"; f.update(); return
            self.simple("alert_time",v)
        self.show(ft.AlertDialog(modal=True,title=ft.Text("وقت التنبيه"),content=f,actions=[ft.TextButton("إلغاء",on_click=lambda _:self.close()),ft.FilledButton("حفظ",on_click=save,style=ft.ButtonStyle(bgcolor=PRIMARY,color="white"))]))

    def edit_days(self,e=None):
        f=ft.TextField(label="عدد الأيام",value=self.db.get_setting("expiry_days","7"),keyboard_type=ft.KeyboardType.NUMBER,text_align=ft.TextAlign.CENTER)
        def save(e):
            v=int(num(f.value,7))
            if not 0<=v<=365: f.error_text="اختر رقماً بين 0 و365"; f.update(); return
            self.simple("expiry_days",str(v))
        self.show(ft.AlertDialog(modal=True,title=ft.Text("أيام التنبيه قبل الانتهاء"),content=f,actions=[ft.TextButton("إلغاء",on_click=lambda _:self.close()),ft.FilledButton("حفظ",on_click=save,style=ft.ButtonStyle(bgcolor=PRIMARY,color="white"))]))

    def simple(self,k,v):
        self.db.set_setting(k,v); self.close(); self.render(); self.toast("تم الحفظ")
        try: self.page.run_task(self.sync_notifications)
        except Exception: pass

    def export_csv(self,e=None):
        try: self.toast(f"تم إنشاء ملف CSV: {self.db.export_csv().name}")
        except Exception as ex: self.toast(f"فشل التصدير: {ex}")

    def backup(self,e=None):
        try: self.toast(f"تم إنشاء النسخة: {self.db.backup_json().name}")
        except Exception as ex: self.toast(f"فشل إنشاء النسخة: {ex}")

    def restore(self,e=None):
        async def pick():
            try:
                files=await self.file_picker.pick_files(allow_multiple=False,with_data=True,allowed_extensions=["json"])
                if not files: return
                if not files[0].bytes: self.toast("تعذر قراءة الملف"); return
                self.db.restore_json(files[0].bytes); self.render(); self.toast("تمت استعادة النسخة الاحتياطية")
                await self.sync_notifications()
            except Exception as ex: self.toast(f"فشل الاستعادة: {ex}")
        try: asyncio.create_task(pick())
        except Exception: self.toast("تعذر فتح مستعرض الملفات")

    def about(self,e=None):
        self.show(ft.AlertDialog(modal=True,title=ft.Text(APP_NAME,weight=ft.FontWeight.BOLD),content=ft.Column(tight=True,controls=[ft.Text("إدارة المخزون وتواريخ الصلاحية"),ft.Text(f"الإصدار {APP_VERSION}",color=MUTED),ft.Divider(),ft.Text("Python + Flet + SQLite",color=MUTED)]),actions=[ft.TextButton("إغلاق",on_click=lambda _:self.close())]))

    def show(self,d):
        try: self.page.show_dialog(d)
        except Exception: self.page.dialog=d; d.open=True; self.page.update()

    def close(self):
        try: self.page.pop_dialog()
        except Exception:
            try:
                if getattr(self.page,"dialog",None): self.page.dialog.open=False; self.page.update()
            except Exception: pass

    def toast(self,msg):
        try: self.page.show_dialog(ft.SnackBar(ft.Text(msg),duration=ft.Duration(seconds=3)))
        except Exception: print(msg)

    async def sync_notifications(self):
        if not self.notifications or self._syncing: return
        self._syncing=True
        try:
            if self.db.get_setting("notifications","1")!="1":
                try: await self.notifications.cancel_all()
                except Exception: pass
                return
            try: await self.notifications.request_permissions()
            except Exception: pass
            try: exact=await self.notifications.can_schedule_exact_notifications()
            except Exception: exact=False
            mode="exact_allow_while_idle" if exact else "inexact_allow_while_idle"
            try: await self.notifications.cancel_all()
            except Exception: pass
            channel="freshstock_alerts"
            try: await self.notifications.create_notification_channel(channel_id=channel,channel_name="تنبيهات FreshStock",channel_description="تنبيهات انتهاء الصلاحية والمخزون المنخفض",importance="high",play_sound=True,enable_vibration=True)
            except Exception: pass
            alert=self.db.get_setting("alert_time","09:00")
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",alert or ""): alert="09:00"
            hh,mm=map(int,alert.split(":")); now=datetime.now(); first=datetime.combine(now.date(),time(hh,mm))
            if first<=now: first+=timedelta(days=1)
            days=int(num(self.db.get_setting("expiry_days","7"),7)); products=self.db.all_products()
            expiry_on=self.db.get_setting("expiry_alerts","1")=="1"; low_on=self.db.get_setting("low_stock","1")=="1"
            warnings=[]
            for p in products:
                st=expiry_status(p.get("expiry_date",""),days)
                if expiry_on and st in ("expired","soon"):
                    d=days_left(p.get("expiry_date","")); text="منتهي" if d is not None and d<0 else ("ينتهي اليوم" if d==0 else f"متبقي {d} يوم")
                    warnings.append(f"{p.get('name','منتج')}: {text}"); continue
                if low_on and num(p.get("minimum_quantity"))>0 and num(p.get("quantity"))<=num(p.get("minimum_quantity")): warnings.append(f"{p.get('name','منتج')}: مخزون منخفض")
            body="لا توجد تنبيهات حالياً." if not warnings else " • ".join(warnings[:6])
            if len(warnings)>6: body+=f" • و{len(warnings)-6} تنبيهات أخرى"
            try: await self.notifications.schedule_notification(notification_id=900001,title="FreshStock — ملخص يومي",body=body,scheduled_time=first,match_date_time_components="time",schedule_mode=mode,channel_id=channel,importance="high",payload="daily_summary")
            except Exception: pass
            if expiry_on:
                for p in products:
                    d=parse_date(p.get("expiry_date")); pid=int(p.get("id") or 0)
                    if not d or pid<=0: continue
                    at=datetime.combine(d-timedelta(days=days),time(hh,mm))
                    if at<=now: continue
                    try: await self.notifications.schedule_notification(notification_id=100000+pid,title="تنبيه صلاحية المنتج",body=f"{p.get('name','منتج')} سينتهي بتاريخ {p.get('expiry_date') }.",scheduled_time=at,schedule_mode=mode,channel_id=channel,importance="high",payload=f"product:{pid}")
                    except Exception: pass
        except Exception as ex: print(f"Notification sync failed: {ex}")
        finally: self._syncing=False


def main(page):
    FreshStock(page).setup()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
