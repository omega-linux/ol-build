from .about import AboutPage
from .appearance import AppearancePage
from .datetime import DateTimePage
from .display import DisplayPage
from .input import InputPage
from .region import RegionPage
from .sound import SoundPage
from .users import UsersPage

# Sidebar order.
PAGES = [DisplayPage, SoundPage, AppearancePage, InputPage, RegionPage, DateTimePage, UsersPage, AboutPage]
