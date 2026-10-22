from django import forms
from .models import BackupSettings

class BackupSettingsForm(forms.ModelForm):
    class Meta:
        model = BackupSettings
        fields = ("enabled", "frequency", "run_time", "weekday", "day_of_month")
        labels = {
            "enabled": "بکاپ خودکار فعال باشد",
            "frequency": "دوره بکاپ",
            "run_time": "ساعت اجرا",
            "weekday": "روز هفته",
            "day_of_month": "روز ماه",
        }
        widgets = {"run_time": forms.TimeInput(format="%H:%M", attrs={"type": "time", "dir": "ltr"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["weekday"].help_text = "برای بکاپ هفتگی استفاده می‌شود."
        self.fields["day_of_month"].help_text = "برای بکاپ ماهانه استفاده می‌شود."
