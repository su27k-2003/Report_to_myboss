import os
import sys
import time
import requests
from waveshare_epd import epd2in9_V2
from datetime import datetime, timedelta
from PIL import Image,ImageDraw,ImageFont
from backports.datetime_fromisoformat import MonkeyPatch
MonkeyPatch.patch_fromisoformat()

# Keep it as absolute path if you want to run the script by cronjob
pic_dir = '/home/pi/Projects/Report_to_myboss/pic'

def load_api_key():
    return os.environ['PAGERDUTY_KEY']


def get_user_id():
    url = 'https://api.pagerduty.com/users/me'
    return pd_api(url)['user']['id']


# PD API call
def pd_api(url, payload=None, method="GET"):
    url = url
    key = load_api_key()
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=key)}
    if payload:
        if method == 'GET':
            r = requests.request(method=method, url=url, headers=headers, params=payload)
        else:
            r = requests.request(method=method, url=url, headers=headers, json=payload)
    else:
        r = requests.request(method=method, url=url, headers=headers)

    r.raise_for_status()
    return r.json()


# On-call Shift Forecast
# As checking PD schedules takes some time and user schdules are not frequently changed，this function will be executed ONLY once when start/restart the script

def shift_forecast():
    global table_shift_forecast
    global dict_schedule
    dict_schedule = {}

    url = 'https://api.pagerduty.com/schedules/'

    # now = current time
    # days_later = today + shift forecast request days (args.shift_forecast, defaul=7 days) - the time already passed today to make "until" in the payload as 00:00:00
    # Without query 00:00:00 format in "until" payload could cause incorrect shift start/end time returned from the PD API
    now = datetime.now()
    days_later = now + timedelta(days = 5) - timedelta(hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)

    payload = {
        "time_zone": "Australia/Sydney",
        "since": now,
        "until": days_later,
    }

    # Check ICD schedule
    for schedule_id in schedule_id_ICD:
        ICD_schedule = pd_api(url=url+schedule_id, payload=payload)
        users = ICD_schedule['schedule']['final_schedule']['rendered_schedule_entries']

        for user in users:
            if user['user']['id'] == user_id:
                shift_start_time = user['start']
                shift_end_time = user['end']
                # To ensure the key is unique and won't be overwritten, add timestamp: str(datetime.now()) to the name of the key
                dict_schedule.update({'ICD_'+str(datetime.now()):[shift_start_time, shift_end_time]})

    # Check mHub schedules
    for schedule_id in schedule_id_mHub:
        mHub_schedule = pd_api(url=url+schedule_id, payload=payload)
        users = mHub_schedule['schedule']['final_schedule']['rendered_schedule_entries']

        for user in users:
            if user['user']['id'] == user_id:
                shift_start_time = user['start']
                shift_end_time = user['end']
                # To ensure the key is unique and won't be overwritten, add timestamp: str(datetime.now()) to the name of the key
                dict_schedule.update({'mHub_'+str(datetime.now()):[shift_start_time, shift_end_time]})

    # Check Cloudant schedules
    for schedule_id in schedule_id_Cloudant:
        Cloudant_schedule = pd_api(url=url+schedule_id, payload=payload)
        users = Cloudant_schedule['schedule']['final_schedule']['rendered_schedule_entries']

        for user in users:
            if user['user']['id'] == user_id:
                shift_start_time = user['start']
                shift_end_time = user['end']
                # To ensure the key is unique and won't be overwritten, add timestamp: str(datetime.now()) to the name of the key
                dict_schedule.update({'Cloudant_'+str(datetime.now()):[shift_start_time, shift_end_time]})

    # Init e-Paper module to disply the output
    epd = epd2in9_V2.EPD()
    epd.init()
    epd.Clear(0xFF)
    font15 = ImageFont.truetype(os.path.join(pic_dir, 'Font.ttc'), 15)
    font18 = ImageFont.truetype(os.path.join(pic_dir, 'Font.ttc'), 18)
    Himage = Image.new('1', (epd.height, epd.width), 255)  # 255: clear the frame
    draw = ImageDraw.Draw(Himage)

    # If no shifts found in shift_forecast days
    if not dict_schedule:
        draw.text((10, 0), "No on-call shifts found in 5 days", font = font18, fill = 0)

    # If shifts found in the next shift_forecast days:
    #   Convert PD datetime format (ISO8601) to normal format by fromisoformat and output shift start/end time from sorted{dict_schedule}
    #   {dict_schedule} is sorted by 'Starts date' to display the date in table_shift_forecast from smallest to largest
    #   Service name = key in {dict_schedule}
    #   Shift start time = datetime.fromisoformat(value[0]).strftime('%a, %d/%m/%Y  %H:%M') in {dict_schedule}, e.g. Monday 13/02/2023 11:00
    #   Shift end time   = datetime.fromisoformat(value[1]).strftime('%a, %d/%m/%Y  %H:%M') in {dict_schedule}, e.g. Monday 13/02/2023 19:00
    #   Shift Duration (hours) = '%.1f' % ((datetime.fromisoformat(value[1]) - datetime.fromisoformat(value[0])).seconds/3600), round up to one decimal places
    else:
        i = 30
        draw.text((10, 0), "5 days on-call shift forecast:", font = font18, fill = 0)

        for key,value in sorted(dict_schedule.items(), key=lambda x:x[1][0]):

            # To remove timestamp from the key name
            if 'ICD' in key:
                key = 'ICD         '
            if 'mHub' in key:
                key = 'mHub     '
            if 'Cloudant' in key:
                key = 'Cloudant'

            # Create table_shift_forecast
            #print(key+': '+datetime.fromisoformat(value[0]).strftime(' %a %d/%m %H:%M')+'-'+datetime.fromisoformat(value[1]).strftime('%H:%M')+', '+'%.1f' % ((datetime.fromisoformat(value[1]) - datetime.fromisoformat(value[0])).seconds/3600) + ' H')
            draw.text((10, i), key+': '+datetime.fromisoformat(value[0]).strftime(' %a %d/%m %H:%M')+'-'+datetime.fromisoformat(value[1]).strftime('%H:%M')+', '+'%.1f' % ((datetime.fromisoformat(value[1]) - datetime.fromisoformat(value[0])).seconds/3600) + ' H', font = font15, fill = 0)
            i = i+20

    epd.display(epd.getbuffer(Himage))
    epd.sleep()


if __name__ == '__main__':
    # Escalation Policies:
    #   PEJGKMF = ICD Service On-Call Escalation (https://ibm.pagerduty.com/escalation_policies#PEJGKMF)
    #   PJQPK6U = Message Hub vNext Escalation Policy (https://ibm.pagerduty.com/escalation_policies#PJQPK6U)
    #   P3ANJLS = Cloudant System Ops (https://ibm.pagerduty.com/escalation_policies#P3ANJLS)

    escalation_policies = ['PEJGKMF','PJQPK6U','P3ANJLS']

    # Service IDs:
    #   ICD:
    #       PIXAFH1 = ICD Service - On-Call (https://ibm.pagerduty.com/service-directory/PIXAFH1)
    #       P1FCJJ2 = ICD Service - EU On-Call (https://ibm.pagerduty.com/service-directory/P1FCJJ2)
    #       PD611DA = ICD BNPP EU Oncall (https://ibm.pagerduty.com/service-directory/PD611DA)
    #       P9HPNJZ = ICD Downstream CIE (https://ibm.pagerduty.com/service-directory/P9HPNJZ)
    #       PEPXYG7 = ICD Prometheus (https://ibm.pagerduty.com/service-directory/PEPXYG7)
    #   mHub:
    #       P9NNPM9 = MHub vNext Non-Production Warn Alerts (https://ibm.pagerduty.com/service-directory/P9NNPM9)
    #       PB87TR6 = Mariposa vNext Daily Ops (https://ibm.pagerduty.com/service-directory/PB87TR6)
    #       PB9JAF1 = Message Hub (Mariposa) Sev 2+ Tickets (https://ibm.pagerduty.com/service-directory/PB9JAF1)
    #       PNU6E0A = Message Hub (Mariposa) Sev 1 Tickets (https://ibm.pagerduty.com/service-directory/PNU6E0A)
    #       PF6X164 = Production Page Alerts(mHub) (https://ibm.pagerduty.com/service-directory/PF6X164)
    #       PRMNHVY = Message Hub SOC Escalation (https://ibm.pagerduty.com/service-directory/PRMNHVY)
    #       PJHCMYV = Non-Prod Page Alerts (https://ibm.pagerduty.com/service-directory/PJHCMYV)
    #       PWA3BRY = event-streams-eu-fr2 (https://ibm.pagerduty.com/service-directory/PWA3BRY)
    #   Cloudant:
    #       P892CDY = Sensu-Ops-Acute (https://ibm.pagerduty.com/service-directory/P892CDY)
    #       PJJCBZ2 = Sensu-Ops-Chronic (https://ibm.pagerduty.com/service-directory/PJJCBZ2)
    #       PBJFR9U = fdb-Sysdig-Ops-Acute (https://ibm.pagerduty.com/service-directory/PBJFR9U)
    #       P7LKJ3F = Cloudant Broker (https://ibm.pagerduty.com/service-directory/P7LKJ3F)
    #       P0W8VFH = Cloudant-FDB-logdna (https://ibm.pagerduty.com/service-directory/P0W8VFH)
    #       PT66K7Q = Pingdom (https://ibm.pagerduty.com/service-directory/PT66K7Q)
    #       PGLJGLE = Sensu-Geo (https://ibm.pagerduty.com/service-directory/PGLJGLE)
    #       P7PFQ9T = cloobot (https://ibm.pagerduty.com/service-directory/P7PFQ9T)
    #       P5O9I3N = sensu-email (https://ibm.pagerduty.com/service-directory/P5O9I3N)
    #       PEKROFY = Website (https://ibm.pagerduty.com/service-directory/PEKROFY)

    service_ids_ICD = ['PIXAFH1','P1FCJJ2','PD611DA','P9HPNJZ','PEPXYG7']
    service_ids_mHub = ['P9NNPM9','PB87TR6','PB9JAF1','PNU6E0A','PF6X164','PRMNHVY','PJHCMYV','PWA3BRY']
    service_ids_Cloudant = ['P892CDY','PJJCBZ2','PBJFR9U','P7LKJ3F','P0W8VFH','PT66K7Q','PGLJGLE','P7PFQ9T','P5O9I3N','PEKROFY']

    # On-call schdule IDs:
    # To check user shift start/end time
    #   ICD:
    #       P7HG28Z = ICD Primary
    #   mHub:
    #       PZ26PH2 = MHub vNext Office Hours Schedule (weekday shift)
    #       PRI2N4F = Message Hub vNext Schedule (weekend shift)
    #   Cloudant:
    #       P6G4FN6 = Cloudant Ops Weekday Pager (weekday shift)
    #       PXYHC1X = Cloudant Ops Weekend Pager (weekend shift)

    schedule_id_ICD = ['P7HG28Z']
    schedule_id_mHub = ['PZ26PH2','PRI2N4F']
    schedule_id_Cloudant = ['P6G4FN6','PXYHC1X']

    user_id = get_user_id()

    # On-call Shift Forecast
    # As checking PD schedules takes some time and user schdules are not frequently changed，this function will be executed ONLY once when start/restart the script
    try:
        shift_forecast()
    except KeyboardInterrupt:
        epd2in9_V2.epdconfig.module_exit()
        exit()
