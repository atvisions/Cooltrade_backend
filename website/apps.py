from django.apps import AppConfig
import os


class WebsiteConfig(AppConfig):
    name = 'website'
    path = os.path.abspath(os.path.dirname(__file__))
