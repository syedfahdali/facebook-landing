from django.db import models
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.models import User
from django.conf import settings
from bs4 import BeautifulSoup
from urllib.parse import quote
import json
from django.utils.timezone import localtime
# ============================
#      CAMPAIGN MODEL
# ============================
class Campaign(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, blank=True, null=True)
    email_template = models.ForeignKey('EmailTemplate', on_delete=models.SET_NULL, null=True, blank=True)
    landing_page = models.ForeignKey('LandingPage', on_delete=models.SET_NULL, null=True, blank=True)
    url = models.URLField(blank=True, null=True)
    launch_date = models.DateTimeField(blank=True, null=True)
    send_emails_by = models.DateTimeField(blank=True, null=True)
    sending_profile = models.ForeignKey('SendingProfile', on_delete=models.SET_NULL, null=True, blank=True)
    groups = models.ManyToManyField('Group', blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    def send_emails(self):
        if self.launch_date and timezone.now() < self.launch_date:
            print(f"[SKIP] Too early for campaign '{self.name}'")
            return

        print(f"[SENDING] Campaign: {self.name}")
        group_emails = [group.email for group in self.groups.all()]
        print(f"[TO] Emails: {group_emails}")

        if not group_emails:
            print("[ABORT] No emails to send.")
            return

        subject = self.email_template.subject
        body = self.email_template.html_body or self.email_template.text_body
        domain = getattr(settings, 'SITE_DOMAIN', 'http://127.0.0.1:8000')

        for email in group_emails:
            try:
                encoded_email = quote(email)
                encoded_campaign_id = quote(str(self.id))
                
                print(f"[DEBUG] Encoded Email: {encoded_email}") 
                print(f"[DEBUG] Encoded Campaign ID: {encoded_campaign_id}")  # Debug print
                    
                tracking_pixel = f'<img src="https://techitexpert.com/tracking/pixel.php?tracking_id={encoded_email}&campaign_id={encoded_campaign_id}" width="1" height="1" style="display:none;" />'
                print(f"[DEBUG] Tracking Pixel URL: {tracking_pixel}")  # Debug print

                redirect_url = f"{domain}/redirect/{self.id}/{quote(email)}"
                soup = BeautifulSoup(body, "html.parser")  # 'body' must be your original HTML email content
                for img in soup.find_all("img"):
                    if not img.find_parent("a"):
                        link_tag = soup.new_tag("a", href=redirect_url)
                        img.wrap(link_tag)

                # Append tracking pixel to the HTML email body
                body_with_tracking = str(soup) + tracking_pixel

                msg = EmailMultiAlternatives(
                    subject=subject,
                    body="This is an HTML email.",
                    from_email=self.sending_profile.smtp_user,
                    to=[email]
                )
                msg.attach_alternative(body_with_tracking, "text/html")
                msg.send()

                Result.objects.create(
                    campaign=self,
                    recipient=email,
                    status='sent'
                )

            except Exception as e:
                print(f"[ERROR] {email}: {e}")
                Result.objects.create(
                    campaign=self,
                    recipient=email,
                    status='error',
                    timestamp=timezone.now()
                )

        # ✅ Mark campaign active
        if self.status != 'active':
            self.status = 'active'
            self.save(update_fields=['status'])


# ============================
#     EMAIL TEMPLATE MODEL
# ============================
class EmailTemplate(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    text_body = models.TextField(blank=True, null=True)
    html_body = models.TextField(blank=True, null=True)
    envelope_sender_email = models.EmailField(max_length=255, blank=True, null=True)
    envelope_sender_name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.name

# ============================
#         LANDING PAGE
# ============================
class LandingPage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    url = models.URLField(unique=True, null=True, blank=True)
    html_content = models.TextField()
    created_at = models.DateTimeField(blank=True, null=True)

# ============================
#         GROUP MODEL
# ============================
class Group(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100, default="Unknown")
    last_name = models.CharField(max_length=100, default="Unknown")
    email = models.EmailField(unique=True, default="default@example.com")
    position = models.CharField(max_length=100, default="N/A")
    number_of_members = models.PositiveIntegerField(default=0)
    modified_date = models.DateTimeField(default=timezone.now)
    csv_file = models.FileField(upload_to='csv_uploads/', blank=True, null=True)

    def __str__(self):
        return self.name

# ============================
#    SENDING PROFILE MODEL
# ============================
class SendingProfile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=True, null=True)
    smtp_host = models.CharField(max_length=255, blank=True, null=True)
    smtp_port = models.PositiveIntegerField(blank=True, null=True)
    smtp_user = models.CharField(max_length=255, blank=True, null=True)
    smtp_password = models.CharField(max_length=255, blank=True, null=True)
    use_tls = models.BooleanField(default=True, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.created_at = timezone.now()
        super().save(*args, **kwargs)

# ============================
#         RESULT MODEL
# ============================
class Result(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='results')
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)
    recipient = models.EmailField()
    email_opened = models.BooleanField(default=False)
    email_open_times = models.TextField(default="[]")  # Store open times as a JSON string
    timestamp = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=50,
        choices=[('sent', 'Sent'), ('opened', 'Opened'), ('clicked', 'Clicked')],
        default='sent'
    )

    from django.utils.timezone import localtime

    def add_open_time(self, timestamp):
        local_time = localtime(timestamp)
        local_time = local_time.replace(microsecond=0)
        open_times = json.loads(self.email_open_times) if self.email_open_times else []
        open_times.append(str(local_time))  # Store as readable string
        self.email_open_times = json.dumps(open_times)
        print(f"[DEBUG] Updated open times: {self.email_open_times}")
        self.save()

    def __str__(self):
        return f"{self.status} for {self.campaign.name} ({self.recipient})"