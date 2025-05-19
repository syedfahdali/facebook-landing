# Django Core Imports
from django.utils.timezone import now
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
import smtplib
from urllib.parse import unquote
import csv 
from .forms import CustomUserCreationForm
from django.utils.encoding import force_str
from django.contrib.sites.shortcuts import get_current_site
from django.utils.encoding import force_bytes
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from .tokens import account_activation_token
from django.utils import timezone
from django.contrib import messages
from django.http import HttpResponse
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .forms import GroupForm
from email import policy
from email.parser import BytesParser
from quopri import decodestring
from django.views.decorators.csrf import csrf_exempt
import os
from django.utils.http import urlsafe_base64_decode ,urlsafe_base64_encode
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.contrib.auth.models import User
from datetime import datetime
from bs4 import BeautifulSoup
from datetime import timedelta
# Local Models and Forms
from .models import (
    Campaign, 
    EmailTemplate, 
    LandingPage, 
    Group,
    SendingProfile, 
    Result
)
from .forms import (
    CampaignForm,
    EmailTemplateForm,
    LandingPageForm,
    SendingProfileForm
)
from .utils import send_campaign_email

# Third Party Imports
import smtplib
import json
import requests
from django.http import JsonResponse

@csrf_exempt
def import_website(request):
    if request.method == 'POST':
        url = request.POST.get('url')
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
            
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Extract base domain for name
            domain = url.split('//')[-1].split('/')[0]
            
            return JsonResponse({
                'status': 'success',
                'html_content': response.text,
                'url': url,
                'domain': domain
            })
        except requests.exceptions.SSLError:
            # Try with SSL verification disabled
            try:
                response = requests.get(url, verify=False, timeout=10)
                domain = url.split('//')[-1].split('/')[0]  # Add this line
                response.raise_for_status()
                return JsonResponse({
                    'status': 'success',
                    'html_content': response.text,
                    'url': url,
                    'domain': domain
                })
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)


#======================#
#  Email Track views   #
#======================#
def track_email_open(request, campaign_id, recipient_email):
    recipient_email = unquote(recipient_email)

    try:
        result = Result.objects.get(campaign_id=campaign_id, recipient=recipient_email)
        print(f"[TRACK] Found result for {recipient_email}")
        result.email_opened = True
        print(f"[TRACK] Adding open time for: {recipient_email}")
        result.add_open_time(timezone.now())
        
        result.save(update_fields=["email_opened"])
        
        print(f"[TRACK] Opened: {recipient_email}")
    except Result.DoesNotExist:
        print(f"[TRACK] NOT FOUND: {recipient_email}")
        pass
    
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!' \
            b'\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02' \
            b'\x4c\x01\x00\x3b'
    return HttpResponse(pixel, content_type="image/gif")

def track_link_click(request, campaign_id, recipient_email):
    print(f"[TRACK] Link clicked by: {recipient_email} in campaign {campaign_id}")
    try:
        result = Result.objects.get(campaign_id=campaign_id, recipient=recipient_email)
        result.link_clicked = True
        result.timestamp = now()
        result.save()
    except Result.DoesNotExist:
        pass

    campaign = Campaign.objects.get(id=campaign_id)
    return redirect(f"http://{campaign.landing_page}")


def track_submission(request, campaign_id, recipient_email):
    campaign = get_object_or_404(Campaign, id=campaign_id)
    result = get_object_or_404(Result, campaign=campaign, recipient=recipient_email)
    result.data_submitted = True
    result.save()
    # Optionally, redirect to a thank you page
    return redirect('/thank-you/')

def redirect_view(request, campaign_id, recipient_email):
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        # Log the click here, if needed
        # Result.objects.create(...)

        # Redirect to the actual landing page
        return redirect(f"http://{campaign.landing_page}")
    except Campaign.DoesNotExist:
        return HttpResponse("Invalid campaign", status=404)
    
    
#======================#
#  Base/Index Views    #
#======================#
@login_required
def index(request):
    return render(request, 'core/index.html')


# Ensure these fields are passed to the template
def campaign_list(request):
    today = timezone.now()

    # Fetch active and archived campaigns
    active_campaigns = active_campaigns = Campaign.objects.filter(user=request.user)
    archived_campaigns = Campaign.objects.filter(status='archived')

    # Fetch all necessary modules (email templates, landing pages, etc.)
    email_templates = EmailTemplate.objects.filter(user=request.user)
    landing_pages = LandingPage.objects.filter(user=request.user)
    sending_profiles = SendingProfile.objects.filter(user=request.user)
    groups = Group.objects.filter(user=request.user)

    # Handle form submission for creating a new campaign
    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            # Save the form data but set the user and status manually
            campaign = form.save(commit=False)
            campaign.user = request.user  # Assign the logged-in user to the campaign

            # Set status as 'active' if the launch date is today or in the future
            if campaign.launch_date and campaign.launch_date <= today:
                campaign.status = 'active'
            else:
                campaign.status = 'draft'  # Set status as 'active' even if launch_date is in the future
            
            campaign.save()  # Save the campaign to the database
            form.save_m2m() 
            # Trigger email sending for the campaign after it's saved
            campaign.send_emails()  # This will send the emails to the selected groups

            print(f"Campaign saved and emails sent for: {campaign.name}")

            # Redirect to campaign list after successful save
            return redirect('campaign_list')
        else:
            # Print form errors for debugging
            print("Form Errors:", form.errors)

    else:
        # Initialize the form when the page is first loaded
        form = CampaignForm()

    # Pass data to the template context for rendering
    return render(request, 'core/campaign_list.html', {
        'active_campaigns': active_campaigns,
        'archived_campaigns': archived_campaigns,
        'email_templates': email_templates,
        'landing_pages': landing_pages,
        'sending_profiles': sending_profiles,
        'groups': groups,
        'form': form,  # Pass the form to the template so it's available for modal submission
    })
        
    
        
#======================#
#  Campaign CRUD       #
#======================#
def new_campaign(request):
    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            # Save the campaign but set the user to the logged-in user
            campaign = form.save(commit=False)
            campaign.user = request.user  # Automatically associate the logged-in user
            campaign.status = 'draft'  # Set initial status to 'draft'
            
            print("I am here in New") 
            campaign.save()

            print(f"New campaign created: {campaign.id}, Status: {campaign.status}")
            return redirect('campaign_list')  # Redirect after successful save
        else:
            print("Form is invalid:", form.errors)  # Print form validation errors if any
    else:
        form = CampaignForm()

    # Fetch related objects to pass to the form
    email_templates = EmailTemplate.objects.filter(user=request.user)
    landing_pages = LandingPage.objects.filter(user=request.user)
    sending_profiles = SendingProfile.objects.filter(user=request.user)
    groups = Group.objects.filter(user=request.user)

    return render(request, 'core/campaign_list.html', {
        'form': form,
        'email_templates': email_templates,
        'landing_pages': landing_pages,
        'sending_profiles': sending_profiles,
        'groups': groups,
    })

def export_campaign_csv(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
    results = Result.objects.filter(campaign=campaign)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{campaign.name}_results.csv"'

    writer = csv.writer(response)
    writer.writerow(['First Name', 'Last Name', 'Email', 'Status', 'Submitted', 'Clicked', 'Reported'])

    for r in results:
        writer.writerow([r.first_name, r.last_name, r.recipient, r.status, r.submitted, r.clicked, r.reported])

    return response


def edit_campaign(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
    
    if request.method == 'POST':
        form = CampaignForm(request.POST, instance=campaign)
        if form.is_valid():
            form.save()
            return redirect('campaign_list')
    else:
        form = CampaignForm(instance=campaign)

    return render(request, 'core/edit_campaign.html', {'form': form, 'campaign': campaign})

def campaign_create(request):
    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.status = 'draft'  
            campaign.user = request.user  # ✅ Associate campaign with logged-in user
            campaign.save()
            print("I am here in create")
            # Optionally send an email
            subject = f"New Campaign: {campaign.name}"
            message = f"Details: {campaign.description}"
            recipient_list = ['recipient1@example.com', 'recipient2@example.com']
            send_campaign_email(subject, message, recipient_list)

            return redirect('campaign_list')
    else:
        form = CampaignForm()
    return render(request, 'core/campaign_form.html', {'form': form})

def archive_campaign(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
    campaign.status = 'archived'
    campaign.save()
    return redirect('campaign_list')
import requests
from datetime import datetime
from django.shortcuts import render, get_object_or_404
from .models import Campaign, Result

def campaign_results(request):
    campaign_id = request.GET.get('campaign_id')
    
    if campaign_id:
        campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
    else:
        campaign = Campaign.objects.filter(user=request.user, status='active').last()
    
    if not campaign:
        return render(request, "core/no_campaign.html", {"message": "No active campaigns found."})

    # Query for results tied to this campaign
    results_qs = Result.objects.filter(campaign=campaign)
    unique_opens = results_qs.filter(email_opened=True).values('recipient').distinct().count()
    results = {
        'total': results_qs.count(),
        'opens': results_qs.filter(email_opened=True).count(),
        #'submissions': results_qs.filter(data_submitted=True).count(),
    }

    # External tracking stats across all group emails
    external_stats = {
        "total_api_opens": 0,
        "first_open_time": None,
        "last_open_time": None,
        "error": None
    }

    all_api_timestamps = []

    try:
        group_emails = campaign.groups.values_list('email', flat=True).distinct()
        for email in group_emails:
            api_url = f"https://techitexpert.com/tracking/api.php?user_email={email}&campaign_id={campaign.id}"
            print("API URL:", api_url)
            response = requests.get(api_url)
            if response.status_code == 200:
                api_data = response.json()
                print("Data:", api_data)
                if api_data:
                    external_stats["total_api_opens"] += len(api_data)
                    all_api_timestamps.extend(entry["tracked_at"] for entry in api_data)
                for entry in api_data:
                    tracked_at = entry["tracked_at"]
                    try:
                        result = Result.objects.get(campaign=campaign, recipient=email)
                            
                            # Add the new open time if it's the first time
                        if not result.email_opened:
                                result.add_open_time(tracked_at)  # Store the open time
                    except Result.DoesNotExist:
                            # If no Result object exists, create a new one
                            print(f"No result found for {email}. Skipping the update.")
            else:
                print(f"API call failed for {email}: {response.status_code}")
    except Exception as e:
        external_stats["error"] = str(e)

    # Convert timestamps to datetime so Django template can use |date filter
    if all_api_timestamps:
        try:
            parsed_times = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for ts in all_api_timestamps]
            external_stats["first_open_time"] = min(parsed_times)
            external_stats["last_open_time"] = max(parsed_times)
        except Exception as e:
            print("Timestamp parse error:", e)
            external_stats["error"] = "Timestamp format error"

    for result in results_qs:
        try:
            result.open_times = [datetime.strptime(time, "%Y-%m-%d %H:%M:%S") for time in json.loads(result.email_open_times)]
        except json.JSONDecodeError:
            result.open_times = [] 
    # Pass the necessary data to the template
    context = {
        'campaign': campaign,
        'results': results,
        'detailed_results': results_qs,  # Pass the queryset for email sent and opened
        'external_stats': external_stats,
        'active_campaigns': Campaign.objects.filter(user=request.user, status='active')
    }

    return render(request, 'core/index.html', context)

def campaign_update(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if request.method == 'POST':
        form = CampaignForm(request.POST, instance=campaign)
        if form.is_valid():
            form.save()
            return redirect('campaign_list')
    else:
        form = CampaignForm(instance=campaign)
    return render(request, 'core/campaign_form.html', {'form': form})

def delete_campaign(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
    campaign.delete()
    return redirect('campaign_list')

def activate_campaign(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
    campaign.status = 'active'
    campaign.save()
    return redirect('campaign_list')


def launch_campaign(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)

    # Debugging: print the campaign data before any updates
    print(f"Before updating - Campaign ID: {campaign.id}, Status: {campaign.status}, Launch Date: {campaign.launch_date}")

    if campaign.launch_date < timezone.now():
        messages.error(request, "❌ The launch date must be today or in the future.")
        return redirect('campaign_list')

    if campaign.send_emails_by and campaign.send_emails_by < timezone.now():
        messages.error(request, "❌ The 'Send emails by' date must be today or in the future.")
        return redirect('campaign_list')

    # Set the campaign status to 'active' and save it
    campaign.status = 'active'
    campaign.save()

    # Debugging: print the campaign data after saving
    print(f"After updating - Campaign ID: {campaign.id}, Status: {campaign.status}, Launch Date: {campaign.launch_date}")

    # Trigger sending emails (this assumes the send_emails method is working)
    campaign.send_emails()  # Assuming the `send_emails` method is properly implemented

    messages.success(request, f"🚀 Campaign '{campaign.name}' has been launched!")
    return redirect('campaign_list')



def result_list(request):
    results = Result.objects.all()
    return render(request, 'core/result_list.html', {'results': results})

#===========================#
#  Email Template CRUD      #
#===========================#
def email_template_list(request):
    email_templates = EmailTemplate.objects.filter(user=request.user)
    return render(request, 'core/email_template_list.html', {'email_templates': email_templates})

@csrf_exempt
def create_email_template(request):
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST)
        if form.is_valid():
            email_template = form.save(commit=False)

            # ✅ Associate the template with the logged-in user
            email_template.user = request.user

            # Handle body types
            body_type = form.cleaned_data.get('body_type')
            if body_type == 'text':
                email_template.html_body = None
            else:  # html
                email_template.text_body = None

            email_template.save()
            return JsonResponse({'success': True})
        else:
            errors = form.errors.get_json_data()
            return JsonResponse({'success': False, 'error': errors})
    else:
        form = EmailTemplateForm()
    return render(request, 'core/create_email_template.html', {'form': form})

def emailtemplate_update(request, pk):
    emailtemplate = get_object_or_404(EmailTemplate, pk=pk)
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST, instance=emailtemplate)
        if form.is_valid():
            email_template = form.save(commit=False)
            body_type = form.cleaned_data['body_type']
            if body_type == 'text':
                email_template.html_body = None
            else:  # html
                email_template.text_body = None
            email_template.save()
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'error': 'Invalid form data', 'details': form.errors.as_json()})
    else:
        form = EmailTemplateForm(instance=emailtemplate)
        return render(request, 'core/create_email_template.html', {'form': form}) # This can be removed if fully modal-based

@login_required
def emailtemplate_delete(request, id):
    try:
        template = get_object_or_404(EmailTemplate, id=id)
        template.delete()
        return JsonResponse({
            'success': True,
            'message': 'Template deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@csrf_exempt
def upload_image(request):
    if request.method == 'POST' and request.FILES.get('upload'):
        uploaded_file = request.FILES['upload']
        file_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uploaded_file.name}"
        file_path = os.path.join(settings.MEDIA_ROOT, 'uploads', file_name)

        # Ensure the directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Save the file
        with open(file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        # Return the URL of the uploaded file
        file_url = f"{settings.MEDIA_URL}uploads/{file_name}"
        return JsonResponse({'url': file_url})

    return JsonResponse({'error': 'Invalid request'}, status=400)

def parse_eml(file):
    try:
        msg = BytesParser(policy=policy.default).parse(file)

        subject = msg.get('subject', '')
        from_address = msg.get('from', '')
        body = None

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == 'text/html':
                    body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    break
        else:
            if msg.get_content_type() == 'text/html':
                body = msg.get_payload(decode=True).decode('utf-8', errors='replace')

        return {
            'subject': subject,
            'from': from_address,
            'body': body or '',  
        }
    except Exception as e:
        raise

def parse_raw_email(request):
    if request.method == 'POST':
        try:
            raw_email = request.POST.get('raw_email', '')
            if not raw_email:
                return JsonResponse({'success': False, 'error': 'No raw email content provided.'})

            # Parse the raw email content
            msg = BytesParser(policy=policy.default).parsebytes(raw_email.encode('utf-8'))

            subject = msg.get('subject', '')
            from_address = msg.get('from', '')
            body = None

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == 'text/html':
                        body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                        break
            else:
                if msg.get_content_type() == 'text/html':
                    body = msg.get_payload(decode=True).decode('utf-8', errors='replace')

            return JsonResponse({
                'success': True,
                'subject': subject,
                'from': from_address,
                'body': body or '',  
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})

def parse_email(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        try:
            email_data = parse_eml(file)
            return JsonResponse({'success': True, **email_data})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})


def copy_email_template(request, pk):
    template = get_object_or_404(EmailTemplate, pk=pk)
    
    # Create a new template with the same data
    new_template = EmailTemplate(
        name=f"Copy of {template.name}",
        subject=template.subject,
        text_body=template.text_body,
        html_body=template.html_body,
        envelope_sender_email=template.envelope_sender_email,
        envelope_sender_name=template.envelope_sender_name,

    )
    new_template.save()
    
    # Redirect to the email template list
    return redirect('email_template_list')

#===========================#
#  Landing Page CRUD        #
#===========================#
def landing_page_list(request):
    landing_pages = LandingPage.objects.filter(user=request.user)
    return render(request, 'core/landing_page_list.html', {'landing_pages': landing_pages})

@csrf_exempt
def parse_website(request):
    if request.method == 'POST':
        try:
            html_content = request.POST.get('html_content', '')
            if not html_content:
                return JsonResponse({'success': False, 'error': 'No HTML content provided.'})

            # Parse HTML and extract body
            soup = BeautifulSoup(html_content, 'html.parser')
            body = soup.body
            body_content = str(body) if body else html_content

            return JsonResponse({
                'success': True,
                'body': body_content,
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})

@csrf_exempt
def create_landing_page(request):
    if request.method == 'POST':
        form = LandingPageForm(request.POST)
        if form.is_valid():
            landing_page = form.save(commit=False)
            landing_page.user = request.user  # ✅ associate with current user
            landing_page.save()
            return JsonResponse({'success': True})
        else:
            print("Form errors:", form.errors)
            return JsonResponse({'error': form.errors}, status=400)
    else:
        form = LandingPageForm()
    return render(request, 'core/create_landing_page.html', {'form': form})

def landingpage_update(request, pk):
    landingpage = get_object_or_404(LandingPage, pk=pk)
    if request.method == 'POST':
        # For AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                landingpage.name = request.POST.get('name')
                landingpage.url = request.POST.get('url', '')
                landingpage.html_content = request.POST.get('html_content')
                landingpage.save()
                return JsonResponse({'status': 'success'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'error': str(e)}, status=400)
        # For regular form submission
        else:
            form = LandingPageForm(request.POST, instance=landingpage)
            if form.is_valid():
                form.save()
                return redirect('landingpage_list')
    else:
        form = LandingPageForm(instance=landingpage)
    return render(request, 'core/landingpage_form.html', {'form': form})

def landingpage_delete(request, pk):
    try:
        landingpage = get_object_or_404(LandingPage, pk=pk)
        landingpage.delete()
        return JsonResponse({
            'success': True,
            'message': 'Landing page deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


#===========================#
#  Sending Profile CRUD     #
#===========================#
# views.py - Modify sending_profile_list view
def sending_profile_list(request):
    if request.method == 'POST':
        name = request.POST.get('p_name')
        smtp_host_port = request.POST.get('host')
        smtp_user = request.POST.get('username')
        smtp_password = request.POST.get('password')
        use_tls = request.POST.get('use_tls', 'false').lower() == 'true'
        smtp_from = request.POST.get('smtp_from')

        # Split host and port
        if ':' in smtp_host_port:
            smtp_host, smtp_port = smtp_host_port.split(':')
        else:
            smtp_host = smtp_host_port
            smtp_port = 587  # Default SMTP port

        # ✅ Associate the profile with the current user
        SendingProfile.objects.create(
            user=request.user,  # <-- REQUIRED
            name=name,
            smtp_host=smtp_host,
            smtp_port=int(smtp_port),
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            use_tls=use_tls,
        )
        return redirect('sending_profile_list')

    # Only show profiles created by this user
    sending_profiles = SendingProfile.objects.filter(user=request.user)
    return render(request, 'core/sending_profile_list.html', {'sending_profiles': sending_profiles})

def create_sending_profile(request):
    return render(request, 'core/create_sending_profile.html')

def sendingprofile_update(request, pk):
    profile = get_object_or_404(SendingProfile, id=pk)
    
    if request.method == "POST":
        form = SendingProfileForm(request.POST, instance=profile)
        if form.is_valid():
            # Handle password separately: only update if provided
            if form.cleaned_data["smtp_password"]:
                profile.smtp_password = form.cleaned_data["smtp_password"]
            form.save()
            return JsonResponse({"status": "success", "message": "Profile updated"})
        else:
            return JsonResponse({"status": "error", "message": form.errors.as_json()}, status=400)
    
    return render(request, "your_template.html", {"profile": profile})

def sendingprofile_delete(request, pk):
    try:
        sendingprofile = get_object_or_404(SendingProfile, pk=pk)
        sendingprofile.delete()
        return JsonResponse({
            'success': True,
            'message': 'Sending profile deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


#======================#
#  Group Management    #
#======================#
def group_list(request):
    groups = Group.objects.filter(user=request.user)
    form = GroupForm()
    return render(request, 'core/group_list.html', {'groups': groups, 'form': form})

def create_group(request):
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            group = form.save(commit=False)
            group.user = request.user  # ✅ Assign current user
            group.save()
    return redirect('group_list')


def update_group(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
    return redirect('group_list')

def delete_group(request, pk):
    try:
        group = get_object_or_404(Group, pk=pk)
        group.delete()
        return JsonResponse({
            'success': True,
            'message': 'Group deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)



#======================#
#  Results & Reporting #
#======================#
def result_list(request):
    results = Result.objects.all()
    return render(request, 'core/result_list.html', {'results': results})


#======================#
#  Email Functionality #
#======================#
# views.py - Update send_test_email view
@csrf_exempt
def send_test_email(request):
    if request.method == "POST":
        try:
            data = request.POST
            smtp_from = data.get("smtp_from")
            recipient_email = data.get("recipient_email")
            host_port = data.get("host")
            
            # Split host and port
            if ':' in host_port:
                smtp_host, smtp_port = host_port.split(':')
            else:
                smtp_host = host_port
                smtp_port = 587

            smtp_username = data.get("username")
            smtp_password = data.get("password")

            # Validate required fields
            if not all([smtp_from, recipient_email, smtp_host, smtp_username, smtp_password]):
                return JsonResponse({"status": "error", "message": "Missing required fields"}, status=400)

            # Create message
            msg = MIMEMultipart()
            msg['From'] = smtp_from
            msg['To'] = recipient_email
            msg['Subject'] = "Test Email from Phishing Simulator"
            body = "This is a test email from your SMTP profile configuration."
            msg.attach(MIMEText(body, 'plain'))

            # Create SMTP connection with timeout
            server = smtplib.SMTP(smtp_host, int(smtp_port), timeout=10)
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(smtp_from, recipient_email, msg.as_string())
            server.quit()

            return JsonResponse({"status": "success", "message": "Test email sent successfully!"})
        
        except smtplib.SMTPAuthenticationError:
            return JsonResponse({
                "status": "error",
                "message": "Authentication failed. Check credentials and ensure you're using an App Password if 2FA is enabled."
            }, status=401)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=400)

def dashboard_view(request):
    return render(request, 'core/dashboard.html', {
        'timestamp': now().timestamp()  # forces cache-bust
    })
def result_dashboard(request):
    # Fetch all campaigns and their results
    campaigns = Campaign.objects.filter(user=request.user)


    # Prepare a dictionary to hold the results for each campaign
    campaign_results = {}

    for campaign in campaigns:
        # Get the results for each campaign
        results = Result.objects.filter(campaign=campaign)

        # Count the number of opens, clicks, and submissions
        opens = results.filter(email_opened=True).count()
        clicks = results.filter(link_clicked=True).count()
        submissions = results.filter(data_submitted=True).count()

        # Add the results to the campaign's data
        campaign_results[campaign] = {
            'opens': opens,
            'clicks': clicks,
            'submissions': submissions,
            'total': results.count(),
        }

    return render(request, 'core/index.html', {
        'campaign_results': campaign_results
    })
#======================#
#  Authentication      #
#======================#
def user_login(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect('index')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'core/login.html', {'form': form})

def user_logout(request):
    logout(request)
    return redirect('index')

def user_register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # Deactivate until email confirmed
            user.save()

            # Email activation logic
            current_site = get_current_site(request)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            activation_link = f"http://{current_site.domain}/activate/{uid}/{token}/"

            subject = 'Activate your PhishSim account'
            from_email = 'noreply@phishsim.com'
            to_email = form.cleaned_data.get('email')

            html_content = render_to_string('core/activation_email.html', {
                'username': user.first_name,
                'activation_link': activation_link,
            })
            text_content = f"Hi {user.first_name},\nActivate your account by visiting this link: {activation_link}"

            email = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
            email.attach_alternative(html_content, "text/html")
            email.send()

            return render(request, 'core/email_sent.html')
    else:
        form = CustomUserCreationForm()
    return render(request, 'core/register.html', {'form': form})
    
def activate(request, uid, token):
    try:
        uid = urlsafe_base64_decode(uid).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        return render(request, 'core/activation_success.html')
    else:
        return render(request, 'core/activation_failed.html')

def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        return render(request, 'core/activation_success.html')  # You can customize this success template
    else:
        return render(request, 'core/activation_failed.html', {'email': user.email})


def resend_activation_email(request):
    email = request.GET.get('email')
    try:
        user = User.objects.get(email=email)
        if not user.is_active:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            activation_link = request.build_absolute_uri(
                reverse('activate', kwargs={'uidb64': uid, 'token': token})
            )

            subject = 'Resend: Activate Your PhishSim Account'
            from_email = settings.DEFAULT_FROM_EMAIL

            html_content = render_to_string('core/activation_email.html', {
                'username': user.first_name,
                'activation_link': activation_link,
            })
            text_content = f"Hi {user.first_name},\nActivate your account by visiting this link: {activation_link}"

            email = EmailMultiAlternatives(subject, text_content, from_email, [user.email])
            email.attach_alternative(html_content, "text/html")
            email.send()

            messages.success(request, 'A new activation email has been sent.')
        else:
            messages.info(request, 'Your account is already active.')
    except User.DoesNotExist:
        messages.error(request, 'No account found with this email.')

    return redirect('login')