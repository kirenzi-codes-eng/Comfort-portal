from pathlib import Path

path = Path(r"C:\Users\DELL\OneDrive\Desktop\COMFORT_PORTAL\app.py")
text = path.read_text(encoding="utf-8")
start = text.index("MODULE_CONFIG = {")
end = text.index("AUTH_MODULE_PATH =")
new = '''MODULE_CONFIG = {
    "Core Workspace": [
        {
            "title": "Home Dashboard",
            "path": SRC / "views" / "home.py",
            "candidates": ["home_view"],
            "icon": "🏠",
        },
        {
            "title": "Subscriptions & Savings",
            "path": SRC / "views" / "savings.py",
            "candidates": ["savings_view"],
            "icon": "💳",
        },
        {
            "title": "Loans Management",
            "path": SRC / "views" / "loans.py",
            "candidates": ["loans_view"],
            "icon": "💼",
        },
        {
            "title": "End-of-Year Sharing",
            "path": SRC / "views" / "sharing.py",
            "candidates": ["sharing_view"],
            "icon": "📈",
        },
    ],
    "Account & Security": [
        {
            "title": "My Profile Settings",
            "path": SRC / "views" / "profile.py",
            "candidates": ["profile_view"],
            "icon": "👤",
        },
        {
            "title": "Kinship Registry",
            "path": SRC / "views" / "family.py",
            "candidates": ["family_view"],
            "icon": "👨‍👩‍👧‍👦",
        },
    ],
}
'''
path.write_text(text[:start] + new + text[end:], encoding="utf-8")
print('updated')
