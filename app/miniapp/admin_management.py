from __future__ import annotations

from aiohttp import web
from sqlalchemy import select

from app.db.models import ServicePeriod, ServicePurchasePlan
from app.mini_app import _validate_init_data


def _month_label(months: int) -> str:
    labels = {1: "یک ماهه", 2: "دو ماهه", 3: "سه ماهه", 6: "شش ماهه", 12: "دوازده ماهه"}
    return labels.get(months, f"{months} ماهه")


def _period_payload(period: ServicePeriod, plans: list[ServicePurchasePlan]) -> dict[str, object]:
    return {
        "id": period.id,
        "name": period.name,
        "months": period.months,
        "duration_days": period.duration_days,
        "service_type": period.service_type,
        "traffic_addon_service_type": period.traffic_addon_service_type,
        "is_active": period.is_active,
        "is_archived": period.is_archived,
        "sort_order": period.sort_order,
        "custom_price_per_gb_toman": period.custom_price_per_gb_toman,
        "custom_min_volume_gb": period.custom_min_volume_gb,
        "custom_max_volume_gb": period.custom_max_volume_gb,
        "plans": [
            {
                "id": item.id,
                "volume_gb": item.volume_gb,
                "duration_days": item.duration_days,
                "price_toman": item.price_toman,
                "is_custom": item.is_custom,
                "is_special_offer": item.is_special_offer,
                "special_offer_price_toman": item.special_offer_price_toman,
            }
            for item in plans
        ],
    }


class AdminServicePeriodAPI:
    """Admin-only Mini App API backed by the same service-period tables as the Bot."""

    def __init__(self, db, bot_token: str, admin_ids: list[int]) -> None:
        self.db = db
        self.bot_token = bot_token
        self.admin_ids = {int(value) for value in admin_ids}

    async def _require_admin(self, request: web.Request) -> int:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        validated = _validate_init_data(init_data, self.bot_token)
        telegram_user = validated["telegram_user"]
        if not isinstance(telegram_user, dict):
            raise web.HTTPUnauthorized(text="Invalid Telegram user data")
        tg_id = int(telegram_user["id"])
        if tg_id not in self.admin_ids:
            raise web.HTTPForbidden(text="Admin access required")
        return tg_id

    async def periods(self, request: web.Request) -> web.Response:
        await self._require_admin(request)
        async with self.db.session() as session:
            result = await session.execute(
                select(ServicePeriod)
                .where(ServicePeriod.is_archived.is_(False))
                .order_by(ServicePeriod.sort_order, ServicePeriod.months)
            )
            periods = result.scalars().all()
            payload = []
            for period in periods:
                plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
                payload.append(_period_payload(period, plans))
            return web.json_response({"periods": payload})

    async def create_period(self, request: web.Request) -> web.Response:
        await self._require_admin(request)
        try:
            body = await request.json()
            months = int(body.get("months", 0))
            if not 1 <= months <= 120:
                raise ValueError
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="months must be an integer between 1 and 120")

        async with self.db.session() as session:
            existing = await ServicePeriod.get_any_by_months(session, months)
            if existing and not existing.is_archived:
                raise web.HTTPConflict(text="This service period already exists")
            if existing and existing.is_archived:
                existing.is_archived = False
                existing.is_active = True
                await session.commit()
                plans = await ServicePurchasePlan.list_by_type(session, existing.service_type)
                return web.json_response(_period_payload(existing, plans))

            service_type = "one_month" if months == 1 else "three_month" if months == 3 else f"period_{months}m"
            addon_type = "traffic_addon_30" if months == 1 else "traffic_addon_90" if months == 3 else f"traffic_addon_{months}m"
            period = ServicePeriod(
                name=f"سرویس‌های {_month_label(months)}",
                months=months,
                duration_days=months * 30,
                service_type=service_type,
                traffic_addon_service_type=addon_type,
                is_active=True,
                is_archived=False,
                sort_order=months,
            )
            session.add(period)
            await session.commit()
            return web.json_response(_period_payload(period, []), status=201)

    async def update_period(self, request: web.Request) -> web.Response:
        await self._require_admin(request)
        try:
            period_id = int(request.match_info["period_id"])
            body = await request.json()
        except (KeyError, ValueError, TypeError):
            raise web.HTTPBadRequest(text="Invalid period request")

        async with self.db.session() as session:
            period = await ServicePeriod.get(session, period_id)
            if not period or period.is_archived:
                raise web.HTTPNotFound(text="Service period not found")

            if "is_active" in body:
                period.is_active = bool(body["is_active"])
            if "custom_price_per_gb_toman" in body:
                value = int(body["custom_price_per_gb_toman"])
                if value < 0:
                    raise web.HTTPBadRequest(text="Invalid custom price")
                period.custom_price_per_gb_toman = value
            if "custom_min_volume_gb" in body:
                value = int(body["custom_min_volume_gb"])
                if value <= 0:
                    raise web.HTTPBadRequest(text="Invalid minimum volume")
                if period.custom_max_volume_gb > 0 and value > period.custom_max_volume_gb:
                    raise web.HTTPBadRequest(text="Minimum volume exceeds maximum volume")
                period.custom_min_volume_gb = value
            if "custom_max_volume_gb" in body:
                value = int(body["custom_max_volume_gb"])
                if value < 0:
                    raise web.HTTPBadRequest(text="Invalid maximum volume")
                if value > 0 and value < period.custom_min_volume_gb:
                    raise web.HTTPBadRequest(text="Maximum volume is below minimum volume")
                period.custom_max_volume_gb = value
            if "sort_order" in body:
                period.sort_order = int(body["sort_order"])

            await session.commit()
            plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
            return web.json_response(_period_payload(period, plans))

    async def archive_period(self, request: web.Request) -> web.Response:
        await self._require_admin(request)
        try:
            period_id = int(request.match_info["period_id"])
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="Invalid period id")
        async with self.db.session() as session:
            period = await ServicePeriod.get(session, period_id)
            if not period:
                raise web.HTTPNotFound(text="Service period not found")
            period.is_active = False
            period.is_archived = True
            await session.commit()
            return web.json_response({"ok": True, "id": period.id, "archived": True})

    async def create_plan(self, request: web.Request) -> web.Response:
        await self._require_admin(request)
        try:
            period_id = int(request.match_info["period_id"])
            body = await request.json()
            volume_gb = int(body.get("volume_gb", 0))
            price_toman = int(body.get("price_toman", 0))
        except (KeyError, ValueError, TypeError):
            raise web.HTTPBadRequest(text="Invalid plan request")
        if volume_gb <= 0 or price_toman <= 0:
            raise web.HTTPBadRequest(text="volume_gb and price_toman must be positive")

        async with self.db.session() as session:
            period = await ServicePeriod.get(session, period_id)
            if not period or period.is_archived:
                raise web.HTTPNotFound(text="Service period not found")
            plan = ServicePurchasePlan(
                service_type=period.service_type,
                volume_gb=volume_gb,
                duration_days=period.duration_days,
                price_toman=price_toman,
                is_custom=False,
                is_special_offer=False,
            )
            session.add(plan)
            await session.commit()
            return web.json_response({"id": plan.id}, status=201)

    async def update_plan(self, request: web.Request) -> web.Response:
        await self._require_admin(request)
        try:
            plan_id = int(request.match_info["plan_id"])
            body = await request.json()
        except (KeyError, ValueError, TypeError):
            raise web.HTTPBadRequest(text="Invalid plan request")
        async with self.db.session() as session:
            plan = await ServicePurchasePlan.get(session, plan_id)
            if not plan:
                raise web.HTTPNotFound(text="Service plan not found")
            if "volume_gb" in body:
                value = int(body["volume_gb"])
                if value <= 0:
                    raise web.HTTPBadRequest(text="Invalid volume")
                plan.volume_gb = value
            if "price_toman" in body:
                value = int(body["price_toman"])
                if value <= 0:
                    raise web.HTTPBadRequest(text="Invalid price")
                plan.price_toman = value
            await session.commit()
            return web.json_response({
                "id": plan.id,
                "volume_gb": plan.volume_gb,
                "duration_days": plan.duration_days,
                "price_toman": plan.price_toman,
            })

    async def delete_plan(self, request: web.Request) -> web.Response:
        await self._require_admin(request)
        try:
            plan_id = int(request.match_info["plan_id"])
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="Invalid plan id")
        async with self.db.session() as session:
            plan = await ServicePurchasePlan.get(session, plan_id)
            if not plan:
                raise web.HTTPNotFound(text="Service plan not found")
            if plan.is_special_offer:
                raise web.HTTPConflict(text="Special-offer plans cannot be deleted here")
            await session.delete(plan)
            await session.commit()
            return web.json_response({"ok": True, "id": plan_id, "deleted": True})


ADMIN_HTML = r'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><script src="https://telegram.org/js/telegram-web-app.js?63"></script><style>body{font-family:system-ui;background:#f4f7fb;color:#101828;margin:0;padding:16px}.wrap{max-width:900px;margin:auto}.card{background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:15px;margin:10px 0}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.btn,input{border:1px solid #d0d5dd;border-radius:10px;padding:10px;background:#fff}button{cursor:pointer}.primary{background:#1677c8;color:#fff;border:0}.danger{background:#d92d20;color:#fff;border:0}.plan{display:flex;justify-content:space-between;gap:8px;align-items:center;border-top:1px solid #eee;padding:10px 0}.muted{color:#667085;font-size:12px}.pill{padding:4px 8px;border-radius:999px;font-size:11px;background:#eef2f6}.on{background:#dcfce7;color:#166534}.off{background:#fee2e2;color:#991b1b}</style></head><body><div class="wrap"><h2>🛡️ مدیریت دوره‌های سرویس</h2><div class="muted">این صفحه مستقیماً از جدول‌های مدیریت دوره‌های فعلی ربات استفاده می‌کند.</div><div class="card"><div class="row"><input id="months" type="number" min="1" max="120" placeholder="تعداد ماه"><button class="btn primary" onclick="createPeriod()">➕ ایجاد دوره</button><button class="btn" onclick="load()">↻ بروزرسانی</button></div></div><div id="root">در حال دریافت…</div></div><script>const tg=window.Telegram?.WebApp;if(tg){tg.ready();tg.expand()}const H={'X-Telegram-Init-Data':tg?.initData||''};const root=document.getElementById('root');const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function api(u,o={}){o.headers={...(o.headers||{}),...H,'Content-Type':'application/json'};const r=await fetch(u,{...o,cache:'no-store'});if(!r.ok)throw new Error(await r.text()||'خطا');return r.json()}function money(n){return Number(n||0).toLocaleString('fa-IR')}async function load(){try{const x=await api('/miniapp/api/admin/periods');root.innerHTML=(x.periods||[]).map(p=>`<div class="card"><div class="row"><b>📅 ${esc(p.name)}</b><span class="pill ${p.is_active?'on':'off'}">${p.is_active?'فعال':'غیرفعال'}</span><span class="muted">${p.duration_days} روز</span><button class="btn" onclick="toggle(${p.id},${!p.is_active})">${p.is_active?'غیرفعال کردن':'فعال کردن'}</button><button class="btn danger" onclick="archivePeriod(${p.id})">آرشیو</button></div><div class="muted">حجم دلخواه: ${p.custom_min_volume_gb||0} تا ${p.custom_max_volume_gb||'نامحدود'} GB • پایه هر گیگ: ${money(p.custom_price_per_gb_toman)} تومان</div><div>${(p.plans||[]).map(x=>`<div class="plan"><span>📦 ${x.volume_gb} GB / ${x.duration_days} روز</span><b>${money(x.price_toman)} تومان</b><span class="row"><button class="btn" onclick="editPlan(${x.id},${x.volume_gb},${x.price_toman})">✏️</button><button class="btn danger" onclick="deletePlan(${x.id})">🗑</button></span></div>`).join('')}</div><div class="row"><input id="v${p.id}" type="number" min="1" placeholder="حجم GB"><input id="c${p.id}" type="number" min="1" placeholder="قیمت تومان"><button class="btn primary" onclick="createPlan(${p.id})">➕ ساخت پلن</button><button class="btn" onclick="editPeriod(${p.id},${p.custom_price_per_gb_toman||0},${p.custom_min_volume_gb||0},${p.custom_max_volume_gb||0})">⚙️ تنظیمات دوره</button></div></div>`).join('')||'<div class="card">دوره‌ای وجود ندارد.</div>'}catch(e){root.innerHTML='<div class="card">❌ '+esc(e.message)+'</div>'}}async function createPeriod(){const months=Number(document.getElementById('months').value);if(!months)return;try{await api('/miniapp/api/admin/periods',{method:'POST',body:JSON.stringify({months})});document.getElementById('months').value='';load()}catch(e){alert(e.message)}}async function toggle(id,active){try{await api('/miniapp/api/admin/periods/'+id,{method:'PATCH',body:JSON.stringify({is_active:active})});load()}catch(e){alert(e.message)}}async function archivePeriod(id){if(!confirm('دوره آرشیو شود؟'))return;try{await api('/miniapp/api/admin/periods/'+id+'/archive',{method:'POST'});load()}catch(e){alert(e.message)}}async function createPlan(id){const v=Number(document.getElementById('v'+id).value),c=Number(document.getElementById('c'+id).value);if(!v||!c)return;try{await api('/miniapp/api/admin/periods/'+id+'/plans',{method:'POST',body:JSON.stringify({volume_gb:v,price_toman:c})});load()}catch(e){alert(e.message)}}async function editPlan(id,v,c){const nv=Number(prompt('حجم GB',v)),nc=Number(prompt('قیمت تومان',c));if(!nv||!nc)return;try{await api('/miniapp/api/admin/plans/'+id,{method:'PATCH',body:JSON.stringify({volume_gb:nv,price_toman:nc})});load()}catch(e){alert(e.message)}}async function deletePlan(id){if(!confirm('پلن حذف شود؟'))return;try{await api('/miniapp/api/admin/plans/'+id,{method:'DELETE'});load()}catch(e){alert(e.message)}}async function editPeriod(id,price,min,max){const np=Number(prompt('مبلغ پایه هر گیگ تومان',price));if(!np)return;const nmin=Number(prompt('حداقل حجم GB',min));const nmax=Number(prompt('حداکثر حجم GB؛ صفر یعنی نامحدود',max));try{await api('/miniapp/api/admin/periods/'+id,{method:'PATCH',body:JSON.stringify({custom_price_per_gb_toman:np,custom_min_volume_gb:nmin,custom_max_volume_gb:nmax})});load()}catch(e){alert(e.message)}}load()</script></body></html>'''


def register_admin_management(app: web.Application, db, bot_token: str, admin_ids: list[int]) -> None:
    controller = AdminServicePeriodAPI(db=db, bot_token=bot_token, admin_ids=admin_ids)
    app.router.add_get("/miniapp/api/admin/periods", controller.periods)
    app.router.add_post("/miniapp/api/admin/periods", controller.create_period)
    app.router.add_patch("/miniapp/api/admin/periods/{period_id}", controller.update_period)
    app.router.add_post("/miniapp/api/admin/periods/{period_id}/archive", controller.archive_period)
    app.router.add_post("/miniapp/api/admin/periods/{period_id}/plans", controller.create_plan)
    app.router.add_patch("/miniapp/api/admin/plans/{plan_id}", controller.update_plan)
    app.router.add_delete("/miniapp/api/admin/plans/{plan_id}", controller.delete_plan)
    async def admin_page(request: web.Request) -> web.Response:
        await controller._require_admin(request)
        return web.Response(text=ADMIN_HTML, content_type="text/html")
    app.router.add_get("/miniapp/admin", admin_page)


__all__ = ["register_admin_management", "AdminServicePeriodAPI"]
