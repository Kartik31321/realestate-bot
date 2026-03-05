# dial_leads.py — run this from your laptop to start a campaign
# pip install requests python-dotenv
 
import requests, csv, time, os, json
from datetime import datetime
from dotenv import load_dotenv
 
load_dotenv()  # reads your local .env file
 
KNOW_API_KEY  = os.getenv('KNOWLARITY_API_KEY')
KNOW_AUTH     = os.getenv('KNOWLARITY_AUTH_TOKEN')
KNOW_CAMPAIGN = os.getenv('KNOWLARITY_CAMPAIGN_ID')
 
def dial_lead(phone, name, city, budget):
    response = requests.post(
        'https://kpi.knowlarity.com/Basic/v1/account/call/campaign/add-numbers/',
        headers={
            'x-api-key': KNOW_API_KEY,
            'Authorization': f'Token {KNOW_AUTH}', # Added 'Token ' prefix
            'Content-Type': 'application/json'
        },
        json={
            'phone_number': phone,
            'campaign_id': KNOW_CAMPAIGN,
            'meta_data': {'name': name, 'city': city, 'budget': budget}
        }
    )
    return response.status_code, response.json()
 
def run_campaign(csv_file, delay_seconds=2, max_calls=None):
    log = []
    with open(csv_file, 'r') as f:
        leads = list(csv.DictReader(f))
 
    if max_calls:
        leads = leads[:max_calls]
 
    print(f'Starting: {len(leads)} leads | {delay_seconds}s between calls')
    now = datetime.now()
    if now.hour < 9 or now.hour >= 21:
        print('ERROR: Outside TRAI-allowed calling hours(9AM-9PM). Stopping.')
        return
 
    for i, lead in enumerate(leads):
        status, result = dial_lead(
            lead['phone'], lead['name'],
            lead.get('city',''), lead.get('budget','')
        )
        print(f'[{i+1}/{len(leads)}] {lead["name"]} {lead["phone"]} -> HTTP {status}')
        log.append({'lead': lead, 'status': status, 'time': str(datetime.now())})
        time.sleep(delay_seconds)
 
    with open('call_log.json', 'w') as f:
        json.dump(log, f, indent=2, default=str)
    print(f'Done. Results saved to call_log.json')
 
if __name__ == '__main__':
    # Start small: 20 calls to test
    run_campaign('leads_clean.csv', delay_seconds=2, max_calls=20)
