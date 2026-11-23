from app.views import admin, assets, auth, checkin, donations, health, practice, shop, titles

routers = [health.router, auth.router, checkin.router, practice.router, shop.router,
           donations.router, admin.router, titles.router, assets.router]
