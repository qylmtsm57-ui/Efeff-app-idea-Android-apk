import asyncio
import csv
import json
from datetime import datetime, date, timedelta, time
from pathlib import Path

import flet as ft

from database import Database, expiry_status, days_left

try:
    from flet_android_notifications import FletAndroidNotifications
except Exception:
    FletAndroidNotifications = None

BG = "#F7F8FC"
CARD = "#FFFFFF"
TEXT = "#1D2433"
MUTED = "#7B8494"
PRIMARY = "#315BEA"
PRIMARY_DARK = "#2346BE"
BORDER = "#E6E9F0"
GREEN = "#16A57A"
RED = "#E85A61"
ORANGE = "#F39A27"
BLUE_LIGHT = "#EAF0FF"


def money(v):
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return "0.00"


def status_meta(product, soon_days):
    st = expiry_status(product.get("expiry_date", ""), soon_days)
    if st == "expired":
        return "منتهي", RED, "#FFF0F1", ft.Icons.ERROR_OUTLINE
    if st == "soon":
        d = days_left(product.get("expiry_date", ""))
        label = "ينتهي اليوم" if d == 0 else f"متبقي {d} يوم"
        return label, ORANGE, "#FFF6E8", ft.Icons.WARNING_AMBER_OUTLINED
    if st == "safe":
        return "سليم", GREEN, "#E9F8F3", ft.Icons.CHECK_CIRCLE_OUTLINE
    return "بدون تاريخ", MUTED, "#F0F2F5", ft.Icons.HELP_OUTLINE


def safe_float(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return 0.0


class FreshStock:
    def __init__(self, page: ft.Page):
        self.page = page
        self.db = Database()
        self.index = 0
        self.search_text = ""
        self.inventory_filter = "all"
        self.settings = {k: self.db.get_setting(k) for k in ["notifications", "low_stock", "expiry_alerts", "expiry_days", "dark_mode", "alert_time"]}
        self.content = ft.Container(expand=True)
        self.nav = self._nav()
        self.file_picker = ft.FilePicker()
        self.page.overlay.append(self.file_picker)
        self.notifications = None
        if FletAndroidNotifications is not None:
            try:
                self.notifications = FletAndroidNotifications(on_notification_tap=self.on_notification_tap)
            except Exception:
                self.notifications = None

    def setup(self):
        p = self.page
        p.title = "FreshStock"
        p.padding = 0
        p.spacing = 0
        p.bgcolor = BG
        p.theme = ft.Theme(font_family="Arial")
        try:
            p.window.prevent_close = False
        except Exception:
            pass
        try:
            p.window.width = 390
            p.window.height = 844
        except Exception:
            pass
        try:
            p.set_allowed_device_orientations([ft.DeviceOrientation.PORTRAIT_UP, ft.DeviceOrientation.PORTRAIT_DOWN])
        except Exception:
            pass
        p.theme_mode = ft.ThemeMode.DARK if self.db.get_setting("dark_mode", "0") == "1" else ft.ThemeMode.LIGHT
        if not self.db.onboarding_done():
            self.show_onboarding()
        else:
            self.render()

    def on_notification_tap(self, e):
        try:
            self.index = 2
            self.render()
        except Exception:
            pass

    async def sync_notifications(self):
        """Rebuild native Android alarms from current inventory/settings."""
        if self.notifications is None:
            return
        try:
            if self.db.get_setting("notifications", "1") != "1":
                await self.notifications.cancel_all()
                return

            await self.notifications.request_permissions()
            exact = await self.notifications.can_schedule_exact_notifications()
            schedule_mode = "exact_allow_while_idle" if exact else "inexact_allow_while_idle"
            await self.notifications.cancel_all()

            channel_id = "freshstock_alerts"
            await self.notifications.create_notification_channel(
                channel_id=channel_id,
                channel_name="تنبيهات FreshStock",
                channel_description="تنبيهات انتهاء الصلاحية والمخزون المنخفض",
                importance="high",
                play_sound=True,
                enable_vibration=True,
            )

            alert_time = self.db.get_setting("alert_time", "09:00")
            try:
                hh, mm = [int(x) for x in alert_time.split(":", 1)]
                hh, mm = max(0, min(23, hh)), max(0, min(59, mm))
            except Exception:
                hh, mm = 9, 0

            now = datetime.now()
            first = datetime.combine(now.date(), time(hh, mm))
            if first <= now:
                first += timedelta(days=1)

            days = int(self.db.get_setting("expiry_days", "7"))
            products = self.db.all_products()
            warnings = []
            for p in products:
                st = expiry_status(p.get("expiry_date", ""), days)
                low = (
                    safe_float(p.get("quantity")) <= safe_float(p.get("minimum_quantity"))
                    and safe_float(p.get("minimum_quantity")) > 0
                )
                if st in ("expired", "soon") and self.db.get_setting("expiry_alerts", "1") == "1":
                    left = days_left(p.get("expiry_date", ""))
                    text = "منتهي" if left is not None and left < 0 else f"متبقي {left} يوم"
                    warnings.append(f"{p.get('name', 'منتج')}: {text}")
                elif low and self.db.get_setting("low_stock", "1") == "1":
                    warnings.append(f"{p.get('name', 'منتج')}: مخزون منخفض")

            body = "لا توجد تنبيهات حالياً." if not warnings else " • ".join(warnings[:6])
            if len(warnings) > 6:
                body += f" • و{len(warnings) - 6} تنبيهات أخرى"

            await self.notifications.schedule_notification(
                notification_id=900001,
                title="FreshStock — ملخص يومي",
                body=body,
                scheduled_time=first,
                match_date_time_components="time",
                schedule_mode=schedule_mode,
                channel_id=channel_id,
                importance="high",
                payload="daily_summary",
            )

            if self.db.get_setting("expiry_alerts", "1") == "1":
                for p in products:
                    expiry = p.get("expiry_date", "")
                    try:
                        d = datetime.strptime(expiry, "%Y-%m-%d").date()
                    except Exception:
                        continue
                    alert_dt = datetime.combine(d - timedelta(days=days), time(hh, mm))
                    if alert_dt <= now:
                        continue
                    nid = 100000 + int(p.get("id") or 0)
                    await self.notifications.schedule_notification(
                        notification_id=nid,
                        title="تنبيه صلاحية المنتج",
                        body=f"{p.get('name', 'منتج')} سينتهي بتاريخ {expiry}.",
                        scheduled_time=alert_dt,
                        schedule_mode=schedule_mode,
                        channel_id=channel_id,
                        importance="high",
                        payload=f"product:{p.get('id')}",
                    )
        except Exception as ex:
            print(f"Notification sync skipped: {ex}")

    def _nav(self):
        return ft.NavigationBar(
            selected_index=0,
            height=72,
            bgcolor="#FFFFFF",
            indicator_color="#EAF0FF",
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.HOME_OUTLINED, selected_icon=ft.Icons.HOME, label="الرئيسية"),
                ft.NavigationBarDestination(icon=ft.Icons.INVENTORY_2_OUTLINED, selected_icon=ft.Icons.INVENTORY_2, label="المخزون"),
                ft.NavigationBarDestination(icon=ft.Icons.NOTIFICATIONS_NONE, selected_icon=ft.Icons.NOTIFICATIONS, label="التنبيهات"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="الإعدادات"),
            ],
            on_change=self.on_nav,
        )

    def show_onboarding(self):
        self.index = 0
        self.page.clean()
        self.page.add(self.onboarding_view())
        self.page.update()

    def onboarding_view(self):
        def finish(_=None):
            self.db.set_onboarding_done(True)
            self.render()

        return ft.Container(
            expand=True,
            bgcolor="#F8F9FE",
            padding=ft.padding.symmetric(horizontal=20, vertical=26),
            content=ft.Column(
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=14,
                controls=[
                    ft.Container(width=74, height=74, border_radius=22, bgcolor=PRIMARY, alignment=ft.Alignment(0,0), content=ft.Icon(ft.Icons.INVENTORY_2, color="white", size=38)),
                    ft.Text("FreshStock", size=25, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Text("إدارة مخزونك وتواريخ الصلاحية بسهولة", size=14, color=MUTED, text_align=ft.TextAlign.CENTER),
                    ft.Container(height=14),
                    ft.FilledButton("المتابعة باستخدام Google", icon=ft.Icons.G_ACCOUNT_BOX, on_click=finish, width=330, height=48, style=ft.ButtonStyle(bgcolor="#4D78F3", color="white", shape=ft.RoundedRectangleBorder(radius=13))),
                    ft.Row([ft.OutlinedButton("  Apple", on_click=finish, expand=True, height=46), ft.FilledButton("Facebook", on_click=finish, expand=True, height=46, style=ft.ButtonStyle(bgcolor="#315BEA", color="white", shape=ft.RoundedRectangleBorder(radius=12)))], spacing=8),
                    ft.Divider(color=BORDER),
                    ft.FilledButton("الدخول محلياً", icon=ft.Icons.PERSON_OUTLINE, on_click=finish, width=330, height=48, style=ft.ButtonStyle(bgcolor="#203047", color="white", shape=ft.RoundedRectangleBorder(radius=13))),
                    ft.Text("يمكنك استخدام التطبيق بدون حساب سحابي", size=11, color=MUTED),
                ],
            ),
        )

    def on_nav(self, e):
        self.index = e.control.selected_index
        self.render()

    def render(self):
        self.page.clean()
        self.nav.selected_index = self.index
        body = [self.home_screen, self.inventory_screen, self.alerts_screen, self.settings_screen][self.index]()
        self.page.add(ft.SafeArea(content=ft.Column(controls=[body, self.nav], expand=True, spacing=0), expand=True))
        self.page.update()

    def header(self, title, subtitle=None, action=None):
        left = ft.IconButton(icon=ft.Icons.NOTIFICATIONS_NONE, icon_color=TEXT, on_click=lambda _: self.set_index(2))
        if action:
            right = action
        else:
            right = ft.Container(width=42, height=42, border_radius=14, bgcolor=PRIMARY, alignment=ft.Alignment(0,0), content=ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color="white"))
        title_col = ft.Column([ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=TEXT), ft.Text(subtitle, size=11, color=MUTED)] if subtitle else [ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=TEXT)], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END)
        return ft.Container(padding=ft.padding.only(left=16,right=16,top=8,bottom=8), content=ft.Row([left, ft.Container(expand=True, content=title_col), right], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

    def set_index(self, i):
        self.index = i
        self.render()

    def stat_card(self, title, value, icon, color):
        return ft.Container(expand=True, padding=13, bgcolor=CARD, border_radius=16, border=ft.border.all(1,BORDER), content=ft.Row([
            ft.Container(width=40,height=40,border_radius=12,bgcolor=color,alignment=ft.Alignment(0,0),content=ft.Icon(icon,color="white",size=20)),
            ft.Column([ft.Text(title,size=11,color=MUTED),ft.Text(str(value),size=22,weight=ft.FontWeight.BOLD,color=TEXT)],spacing=1,horizontal_alignment=ft.CrossAxisAlignment.END)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

    def home_screen(self):
        c = self.db.counts()
        products = self.db.all_products()
        soon_days = int(self.db.get_setting("expiry_days", "7"))
        upcoming = [p for p in products if expiry_status(p.get("expiry_date",""), soon_days) in ("expired","soon")][:4]
        search = ft.TextField(hint_text="ابحث عن منتج أو باركود...", prefix_icon=ft.Icons.SEARCH, height=48, border_radius=14, bgcolor="white", border_color=BORDER, text_align=ft.TextAlign.RIGHT, on_change=self.on_home_search)
        if not upcoming:
            list_control = ft.Container(padding=20, alignment=ft.Alignment(0,0), content=ft.Column([ft.Container(width=64,height=64,border_radius=32,bgcolor=BLUE_LIGHT,alignment=ft.Alignment(0,0),content=ft.Icon(ft.Icons.INVENTORY_2_OUTLINED,color=PRIMARY,size=30)), ft.Text("لا توجد منتجات تحتاج إلى إجراء", size=15, weight=ft.FontWeight.BOLD, color=TEXT), ft.Text("أضف المنتجات وسيتم حساب الصلاحية تلقائياً", size=12, color=MUTED, text_align=ft.TextAlign.CENTER)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8))
        else:
            list_control = ft.Column([self.product_card(p, compact=True) for p in upcoming], spacing=8)
        return ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, controls=[
            self.header("FreshStock", "إدارة المخزون والصلاحية"),
            ft.Container(padding=ft.padding.symmetric(horizontal=16), content=search),
            ft.Container(padding=ft.padding.only(left=16,right=16,top=12), content=ft.Container(padding=14,bgcolor="#FFF4DE",border_radius=16,border=ft.border.all(1,"#F7D99C"),content=ft.Row([ft.Icon(ft.Icons.LIGHTBULB_OUTLINED,color=ORANGE),ft.Column([ft.Text("نظام الصلاحية الذكي",weight=ft.FontWeight.BOLD,color=TEXT),ft.Text("يُرتب المنتجات حسب FEFO لتقليل الهدر",size=11,color=MUTED)],spacing=2,expand=True)],rtl=True))),
            ft.Container(padding=ft.padding.all(16), content=ft.Column([ft.Row([self.stat_card("المنتجات",c["total"],ft.Icons.INVENTORY_2_OUTLINED,PRIMARY),self.stat_card("منتهية",c["expired"],ft.Icons.ERROR_OUTLINE,RED)],spacing=9),ft.Row([self.stat_card("قريبة الانتهاء",c["soon"],ft.Icons.WARNING_AMBER_OUTLINED,ORANGE),self.stat_card("مخزون منخفض",c["low"],ft.Icons.TRENDING_DOWN,ft.Colors.PURPLE)],spacing=9)],spacing=9)),
            ft.Container(padding=ft.padding.only(left=16,right=16,top=2,bottom=8), content=ft.Row([ft.Text("الأولوية الآن",size=17,weight=ft.FontWeight.BOLD,color=TEXT),ft.TextButton("عرض الكل",on_click=lambda _: self.set_index(1))],alignment=ft.MainAxisAlignment.SPACE_BETWEEN)),
            ft.Container(padding=ft.padding.symmetric(horizontal=16), content=list_control),
            ft.Container(height=12)
        ])

    def on_home_search(self,e):
        q=e.control.value.strip().lower()
        if q:
            self.search_text=q
            self.index=1
            self.render()

    def product_card(self, p, compact=False):
        soon_days=int(self.db.get_setting("expiry_days","7"))
        label,color,bg,icon=status_meta(p,soon_days)
        qty=money(p.get("quantity",0)).rstrip("0").rstrip(".")
        return ft.Container(padding=12,bgcolor=CARD,border_radius=15,border=ft.border.all(1,BORDER),on_click=lambda _: self.product_details(p["id"]), content=ft.Row([
            ft.Container(width=42,height=42,border_radius=13,bgcolor=bg,alignment=ft.Alignment(0,0),content=ft.Icon(icon,color=color,size=21)),
            ft.Column([ft.Text(p.get("name") or "بدون اسم",size=14,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text(f"الكمية: {qty} {p.get('unit','قطعة')}",size=11,color=MUTED),ft.Text(f"الانتهاء: {p.get('expiry_date') or 'غير محدد'}",size=11,color=MUTED)],spacing=2,expand=True,horizontal_alignment=ft.CrossAxisAlignment.END),
            ft.Container(padding=ft.padding.symmetric(horizontal=8,vertical=5),bgcolor=bg,border_radius=10,content=ft.Text(label,size=10,weight=ft.FontWeight.BOLD,color=color))
        ],rtl=True))

    def inventory_screen(self):
        products=self.db.all_products()
        q=self.search_text.lower().strip()
        if q:
            products=[p for p in products if q in (p.get("name") or "").lower() or q in (p.get("barcode") or "").lower()]
        days=int(self.db.get_setting("expiry_days","7"))
        if self.inventory_filter=="expired": products=[p for p in products if expiry_status(p.get("expiry_date",""),days)=="expired"]
        elif self.inventory_filter=="soon": products=[p for p in products if expiry_status(p.get("expiry_date",""),days)=="soon"]
        elif self.inventory_filter=="low":
            products=[p for p in products if safe_float(p.get("quantity"))<=safe_float(p.get("minimum_quantity"))]
        search=ft.TextField(value=self.search_text,hint_text="بحث بالاسم أو الباركود",prefix_icon=ft.Icons.SEARCH,height=48,border_radius=14,bgcolor="white",border_color=BORDER,text_align=ft.TextAlign.RIGHT,on_change=lambda e:self.inventory_search(e))
        filters=ft.Row(scroll=ft.ScrollMode.AUTO,controls=[self.filter_chip("الكل","all"),self.filter_chip("قريب الانتهاء","soon"),self.filter_chip("منتهي","expired"),self.filter_chip("منخفض","low")],spacing=7)
        list_view=ft.Column([self.product_card(p) for p in products],spacing=8) if products else ft.Container(padding=40,alignment=ft.Alignment(0,0),content=ft.Column([ft.Icon(ft.Icons.SEARCH_OFF,size=42,color=MUTED),ft.Text("لا توجد نتائج",size=16,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text("جرّب تغيير البحث أو الفلتر",size=12,color=MUTED)],horizontal_alignment=ft.CrossAxisAlignment.CENTER,spacing=7))
        fab=ft.FloatingActionButton(icon=ft.Icons.ADD,on_click=lambda _:self.product_form(),bgcolor=PRIMARY,foreground_color="white",mini=True)
        return ft.Column(expand=True,controls=[self.header("المخزون",f"{len(products)} منتج",ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE,icon_color=PRIMARY,on_click=lambda _:self.product_form())),ft.Container(padding=ft.padding.symmetric(horizontal=16),content=search),ft.Container(padding=ft.padding.only(left=16,right=16,top=10,bottom=6),content=filters),ft.Container(expand=True,padding=ft.padding.symmetric(horizontal=16),content=ft.Column(scroll=ft.ScrollMode.AUTO,controls=[list_view])),ft.Container(padding=10,alignment=ft.Alignment(1,0),content=fab)])

    def filter_chip(self,label,value):
        active=self.inventory_filter==value
        return ft.Container(padding=ft.padding.symmetric(horizontal=12,vertical=7),border_radius=18,bgcolor=PRIMARY if active else "#FFFFFF",border=ft.border.all(1,PRIMARY if active else BORDER),on_click=lambda _:self.set_filter(value),content=ft.Text(label,size=11,weight=ft.FontWeight.BOLD,color="white" if active else MUTED))

    def set_filter(self,v):
        self.inventory_filter=v
        self.render()

    def inventory_search(self,e):
        self.search_text=e.control.value
        self.render()

    def product_form(self, product=None):
        editing=product is not None
        if isinstance(product,int): product=self.db.get_product(product)
        p=product or {}
        fields={}
        def field(key,label,icon,value=None,keyboard=None):
            fields[key]=ft.TextField(label=label,value=str(p.get(key, value or "")),prefix_icon=icon,text_align=ft.TextAlign.RIGHT,border_radius=12,border_color=BORDER,bgcolor="#FFFFFF",keyboard_type=keyboard,height=48)
            return fields[key]
        content=ft.Column(scroll=ft.ScrollMode.AUTO,spacing=10,controls=[
            field("name","اسم المنتج",ft.Icons.LABEL_OUTLINE),
            ft.Row([field("quantity","الكمية",ft.Icons.NUMB_1,keyboard=ft.KeyboardType.NUMBER),field("unit","الوحدة",ft.Icons.STRAIGHTEN)],spacing=8),
            ft.Row([field("category","التصنيف",ft.Icons.CATEGORY_OUTLINED),field("barcode","الباركود",ft.Icons.QR_CODE_SCANNER)],spacing=8),
            ft.Row([field("production_date","تاريخ الإنتاج",ft.Icons.CALENDAR_MONTH),field("expiry_date","تاريخ الانتهاء",ft.Icons.EVENT_BUSY)],spacing=8),
            ft.Row([field("minimum_quantity","الحد الأدنى",ft.Icons.WARNING_AMBER_OUTLINED,keyboard=ft.KeyboardType.NUMBER),field("price","السعر",ft.Icons.PAYMENTS_OUTLINED,keyboard=ft.KeyboardType.NUMBER)],spacing=8),
            field("notes","ملاحظات",ft.Icons.NOTES_OUTLINED),
            ft.Text("استخدم الصيغة YYYY-MM-DD للتواريخ",size=10,color=MUTED)
        ])
        def save(_):
            name=fields["name"].value.strip()
            if not name:
                fields["name"].error_text="اسم المنتج مطلوب"
                fields["name"].update();return
            data={k:fields[k].value.strip() for k in fields}
            data["quantity"]=safe_float(data["quantity"]);data["minimum_quantity"]=safe_float(data["minimum_quantity"]);data["price"]=safe_float(data["price"])
            if editing:self.db.update_product(p["id"],data)
            else:self.db.add_product(data)
            self.page.pop_dialog();self.render();self.toast("تم حفظ المنتج بنجاح")
            try:self.page.run_task(self.sync_notifications)
            except Exception:pass
        dialog=ft.AlertDialog(modal=True,title=ft.Text("تعديل المنتج" if editing else "إضافة منتج",weight=ft.FontWeight.BOLD),content=ft.Container(width=390,content=content),actions=[ft.TextButton("إلغاء",on_click=lambda _:self.page.pop_dialog()),ft.FilledButton("حفظ",icon=ft.Icons.SAVE,on_click=save,style=ft.ButtonStyle(bgcolor=PRIMARY,color="white"))],actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        self.page.show_dialog(dialog)

    def product_details(self, product_id):
        p=self.db.get_product(product_id)
        if not p:return
        label,color,bg,icon=status_meta(p,int(self.db.get_setting("expiry_days","7")))
        def delete(_):
            self.page.pop_dialog();self.confirm_delete(p)
        dialog=ft.AlertDialog(modal=True,title=ft.Text(p.get("name","منتج"),weight=ft.FontWeight.BOLD),content=ft.Column([ft.Container(padding=12,bgcolor=bg,border_radius=14,content=ft.Row([ft.Icon(icon,color=color),ft.Text(label,weight=ft.FontWeight.BOLD,color=color)])),self.info_row("الباركود",p.get("barcode") or "—"),self.info_row("الكمية",f"{money(p.get('quantity'))} {p.get('unit','قطعة')}"),self.info_row("التصنيف",p.get("category") or "—"),self.info_row("تاريخ الإنتاج",p.get("production_date") or "—"),self.info_row("تاريخ الانتهاء",p.get("expiry_date") or "—"),self.info_row("السعر",money(p.get("price"))),self.info_row("الحد الأدنى",money(p.get("minimum_quantity"))),self.info_row("الملاحظات",p.get("notes") or "—")],spacing=5,scroll=ft.ScrollMode.AUTO),actions=[ft.TextButton("حذف",icon=ft.Icons.DELETE_OUTLINE,on_click=delete,style=ft.ButtonStyle(color=RED)),ft.FilledButton("تعديل",icon=ft.Icons.EDIT,on_click=lambda _: (self.page.pop_dialog(),self.product_form(p)),style=ft.ButtonStyle(bgcolor=PRIMARY,color="white"))],actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        self.page.show_dialog(dialog)

    def info_row(self,k,v):
        return ft.Container(padding=ft.padding.symmetric(vertical=7),border=ft.border.only(bottom=ft.BorderSide(1,BORDER)),content=ft.Row([ft.Text(str(v),size=12,color=TEXT,expand=True),ft.Text(k,size=11,color=MUTED)],rtl=True))

    def confirm_delete(self,p):
        def yes(_):
            self.db.delete_product(p["id"]);self.page.pop_dialog();self.render();self.toast("تم حذف المنتج")
            try:self.page.run_task(self.sync_notifications)
            except Exception:pass
        d=ft.AlertDialog(modal=True,title=ft.Text("حذف المنتج"),content=ft.Text(f"هل تريد حذف «{p.get('name')}» نهائياً؟"),actions=[ft.TextButton("إلغاء",on_click=lambda _:self.page.pop_dialog()),ft.TextButton("حذف",on_click=yes,style=ft.ButtonStyle(color=RED))])
        self.page.show_dialog(d)

    def alerts_screen(self):
        products=self.db.all_products();days=int(self.db.get_setting("expiry_days","7"));items=[]
        for p in products:
            st=expiry_status(p.get("expiry_date",""),days)
            low=safe_float(p.get("quantity"))<=safe_float(p.get("minimum_quantity"))
            if st in ("expired","soon") or low:items.append((p,st,low))
        if not items:
            body=ft.Container(expand=True,alignment=ft.Alignment(0,0),content=ft.Column([ft.Icon(ft.Icons.NOTIFICATIONS_OFF_OUTLINED,size=48,color=MUTED),ft.Text("لا توجد تنبيهات",size=16,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text("كل شيء تحت السيطرة حالياً",size=12,color=MUTED)],horizontal_alignment=ft.CrossAxisAlignment.CENTER,spacing=8))
        else:
            cards=[]
            for p,st,low in items:
                title="منتج منتهي" if st=="expired" else ("منتج قريب من الانتهاء" if st=="soon" else "مخزون منخفض")
                color=RED if st=="expired" else ORANGE if st=="soon" else PRIMARY
                cards.append(ft.Container(padding=12,bgcolor=CARD,border_radius=15,border=ft.border.all(1,BORDER),content=ft.Row([ft.Container(width=40,height=40,border_radius=12,bgcolor=color,alignment=ft.Alignment(0,0),content=ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE,color="white")),ft.Column([ft.Text(title,size=13,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text(p.get("name",""),size=12,color=MUTED),ft.Text(f"الانتهاء: {p.get('expiry_date') or '—'}   •   الكمية: {money(p.get('quantity'))}",size=10,color=MUTED)],spacing=2,expand=True,horizontal_alignment=ft.CrossAxisAlignment.END)],rtl=True)))
            body=ft.Column(scroll=ft.ScrollMode.AUTO,controls=cards,spacing=8)
        return ft.Column(expand=True,controls=[self.header("التنبيهات",f"{len(items)} تنبيه"),ft.Container(padding=16,content=body,expand=True)])

    def settings_screen(self):
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,controls=[self.header("الإعدادات","التخصيص والنسخ الاحتياطي"),ft.Container(padding=16,content=ft.Column(spacing=10,controls=[
            self.section_title("التنبيهات"),
            self.switch_tile("تشغيل التنبيهات", "notifications", ft.Icons.NOTIFICATIONS_OUTLINED),
            self.switch_tile("تنبيه انخفاض المخزون", "low_stock", ft.Icons.INVENTORY_2_OUTLINED),
            self.switch_tile("تنبيه قرب انتهاء الصلاحية", "expiry_alerts", ft.Icons.EVENT_OUTLINED),
            self.setting_action("وقت التنبيه اليومي", self.db.get_setting("alert_time","09:00"), ft.Icons.ACCESS_TIME, self.edit_alert_time),
            self.setting_action("أيام التنبيه قبل الانتهاء", f"{self.db.get_setting('expiry_days','7')} أيام", ft.Icons.DATE_RANGE, self.edit_expiry_days),
            self.section_title("البيانات"),
            self.setting_action("تصدير CSV", "حفظ نسخة من المنتجات", ft.Icons.DOWNLOAD, self.export_csv),
            self.setting_action("نسخة احتياطية JSON", "حفظ كل البيانات والإعدادات", ft.Icons.BACKUP_OUTLINED, self.backup),
            self.setting_action("استعادة نسخة", "استيراد ملف JSON", ft.Icons.RESTORE, self.restore_backup),
            self.section_title("المظهر"),
            self.switch_tile("الوضع الداكن", "dark_mode", ft.Icons.DARK_MODE_OUTLINED),
            self.setting_action("حول التطبيق", "FreshStock 1.0.0", ft.Icons.INFO_OUTLINE, self.about),
            ft.Container(height=18),
            ft.Text("نسخة Python + Flet مهيأة للهواتف Android",size=10,color=MUTED,text_align=ft.TextAlign.CENTER),
        ]))])

    def section_title(self,t):
        return ft.Container(padding=ft.padding.only(top=8,bottom=2),content=ft.Text(t,size=13,weight=ft.FontWeight.BOLD,color=PRIMARY))

    def switch_tile(self,title,key,icon):
        val=self.db.get_setting(key,"0")=="1"
        return ft.Container(padding=12,bgcolor=CARD,border_radius=14,border=ft.border.all(1,BORDER),content=ft.Row([ft.Switch(value=val,on_change=lambda e:self.toggle_setting(key,e.control.value)),ft.Column([ft.Text(title,size=13,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text("مفعّل" if val else "متوقف",size=10,color=MUTED)],spacing=2,expand=True,horizontal_alignment=ft.CrossAxisAlignment.END),ft.Icon(icon,color=MUTED)],rtl=True))

    def toggle_setting(self,key,value):
        self.db.set_setting(key,"1" if value else "0")
        if key=="dark_mode": self.page.theme_mode=ft.ThemeMode.DARK if value else ft.ThemeMode.LIGHT
        self.render()
        try:self.page.run_task(self.sync_notifications)
        except Exception:pass

    def setting_action(self,title,subtitle,icon,callback):
        return ft.Container(padding=12,bgcolor=CARD,border_radius=14,border=ft.border.all(1,BORDER),on_click=callback,content=ft.Row([ft.Icon(ft.Icons.CHEVRON_LEFT,color=MUTED),ft.Column([ft.Text(title,size=13,weight=ft.FontWeight.BOLD,color=TEXT),ft.Text(subtitle,size=10,color=MUTED)],spacing=2,expand=True,horizontal_alignment=ft.CrossAxisAlignment.END),ft.Container(width=38,height=38,border_radius=11,bgcolor=BLUE_LIGHT,alignment=ft.Alignment(0,0),content=ft.Icon(icon,color=PRIMARY,size=20))],rtl=True))

    def edit_alert_time(self,_=None):
        field=ft.TextField(label="الوقت",value=self.db.get_setting("alert_time","09:00"),text_align=ft.TextAlign.CENTER)
        d=ft.AlertDialog(modal=True,title=ft.Text("وقت التنبيه"),content=field,actions=[ft.TextButton("إلغاء",on_click=lambda _:self.page.pop_dialog()),ft.FilledButton("حفظ",on_click=lambda _:self.save_simple_setting("alert_time",field.value))])
        self.page.show_dialog(d)

    def edit_expiry_days(self,_=None):
        field=ft.TextField(label="عدد الأيام",value=self.db.get_setting("expiry_days","7"),keyboard_type=ft.KeyboardType.NUMBER,text_align=ft.TextAlign.CENTER)
        d=ft.AlertDialog(modal=True,title=ft.Text("أيام التنبيه قبل الانتهاء"),content=field,actions=[ft.TextButton("إلغاء",on_click=lambda _:self.page.pop_dialog()),ft.FilledButton("حفظ",on_click=lambda _:self.save_simple_setting("expiry_days",field.value))])
        self.page.show_dialog(d)

    def save_simple_setting(self,key,value):
        self.db.set_setting(key,value);self.page.pop_dialog();self.render();self.toast("تم الحفظ")
        try:self.page.run_task(self.sync_notifications)
        except Exception:pass

    def export_csv(self,_=None):
        path=self.db.export_csv();self.toast(f"تم إنشاء ملف CSV: {path.name}")

    def backup(self,_=None):
        path=self.db.backup_json();self.toast(f"تم إنشاء النسخة: {path.name}")

    def restore_backup(self,_=None):
        async def pick():
            files=await self.file_picker.pick_files(allow_multiple=False,with_data=True,allowed_extensions=["json"])
            if files:
                try:self.db.restore_json(files[0].bytes);self.render();self.toast("تمت استعادة النسخة الاحتياطية")
                except Exception as ex:self.toast(f"فشل الاستعادة: {ex}")
        asyncio.create_task(pick())

    def about(self,_=None):
        self.page.show_dialog(ft.AlertDialog(title=ft.Text("FreshStock"),content=ft.Text("إدارة المخزون وتواريخ الصلاحية\n\nالإصدار 1.0.0\nPython + Flet + SQLite"),actions=[ft.TextButton("إغلاق",on_click=lambda _:self.page.pop_dialog())]))

    def toast(self,msg):
        self.page.show_dialog(ft.SnackBar(ft.Text(msg),duration=ft.Duration(seconds=3)))



def main(page: ft.Page):
    app=FreshStock(page)
    app.setup()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
