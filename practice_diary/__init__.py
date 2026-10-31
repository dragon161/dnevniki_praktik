"""Работа с представлениями на практику и генерация дневников."""
from .models import Group, Student
from .predstavlenie import Predstavlenie
from .diary import DiaryOptions, generate_diary

__all__ = ["Group", "Student", "Predstavlenie", "DiaryOptions", "generate_diary"]
