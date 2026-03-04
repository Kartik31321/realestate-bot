
# main.py — Sarvam AI + Knowlarity Middleware Server
# Deploy on Railway.app via GitHub
 
import os, json, base64, asyncio
import aiohttp
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from datetime import datetime
from dotenv import load_dotenv
 
load_dotenv()
app = FastAPI(title='Real Estate Voice Bot')
 
# ── Config ────────────────────────────────────────────────────────────────
SARVAM_KEY    = os.getenv('SARVAM_API_KEY')
KNOW_API_KEY  = os.getenv('KNOWLARITY_API_KEY')
KNOW_AUTH     = os.getenv('KNOWLARITY_AUTH_TOKEN')
KNOW_CAMPAIGN = os.getenv('KNOWLARITY_CAMPAIGN_ID')
KNOW_FROM_NUM = os.getenv('KNOWLARITY_VIRTUAL_NUMBER')
AGENT_EXT     = os.getenv('AGENT_EXTENSION')  # e.g. 200
 
# ── In-memory conversation store (per call_id) ────────────────────────────
# NOTE: Railway restarts clear memory. For persistence, add Redis later.
conversations = {}
 
# ── Real Estate System Prompt ─────────────────────────────────────────────
SYSTEM_PROMPT = '''
You are Priya, a friendly real estate assistant at SKJ Landbase.
You are calling leads who showed interest in buying property.
 
YOUR GOAL: Qualify the lead by collecting these 4 details in order:
1. Budget range (50 lakh, 80 lakh, 1 crore, above 1.5 crore)
2. Preferred location or area in the city
3. BHK type (1BHK, 2BHK, 3BHK, villa, plot)
4. Purchase timeline (immediately, 3 months, 6 months, exploring)
 
RULES:
- Keep every response SHORT: 1 to 2 sentences only. This is a phone call.
- Ask only ONE question per response.
- Respond in the same language the lead speaks.
- Hindi leads: respond in simple Hindi.
- If lead is interested in site visit: include the word TRANSFER at the end.
- If lead is not interested: include the word ENDCALL at the end.
- Never quote pricing. Say: Our advisor will share full details.
'''
 
# ═══════════════════════════════════════════════════════════════════════════
# HEALTH CHECK — Railway uses this to confirm server is running
# ═══════════════════════════════════════════════════════════════════════════
@app.get('/health')
async def health():
    return {'status': 'ok', 'service': 'realestate-bot'}
 
# ═══════════════════════════════════════════════════════════════════════════
# KNOWLARITY WEBHOOK — called after lead speaks during an OBD call
# ═══════════════════════════════════════════════════════════════════════════
@app.post('/webhook')
async def knowlarity_webhook(request: Request, background: BackgroundTasks):
    data = await request.json()
 
    call_id     = data.get('call_id', '')
    phone       = data.get('caller_id', '')
    event_type  = data.get('event', 'speech')
    record_url  = data.get('recording_url', '')
 
    # Knowlarity sends post_call event when call ends
    if event_type == 'post_call':
        background.add_task(log_call_outcome, call_id, phone, data)
        conversations.pop(call_id, None)  # clean up memory
        return JSONResponse({'status': 'logged'})
 
    # Step 1: Download the customer's audio from Knowlarity
    audio_bytes = b''
    if record_url:
        async with aiohttp.ClientSession() as s:
            async with s.get(record_url) as r:
                audio_bytes = await r.read()
 
    # Step 2: Sarvam STT — convert speech to text
    transcript = await sarvam_stt(audio_bytes)
    print(f'[{call_id}] Lead said: {transcript}')
 
    # Step 3: Sarvam Chat — get AI reply
    if call_id not in conversations:
        conversations[call_id] = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    conversations[call_id].append({'role': 'user', 'content': transcript})
 
    reply = await sarvam_chat(conversations[call_id])
    conversations[call_id].append({'role': 'assistant', 'content': reply})
    print(f'[{call_id}] Bot replies: {reply[:80]}')
 
    # Step 4: Check for special commands in reply
    do_transfer = 'TRANSFER' in reply
    do_endcall  = 'ENDCALL'  in reply
    clean_reply = reply.replace('TRANSFER','').replace('ENDCALL','').strip()
 
    # Step 5: Sarvam TTS — convert reply to audio
    audio_b64 = await sarvam_tts(clean_reply)
 
    # Step 6: If hot lead, trigger transfer to agent
    if do_transfer:
        background.add_task(transfer_to_agent, call_id)
 
    # Return audio to Knowlarity to play to the lead
    return JSONResponse({
        'audio': audio_b64,
        'text': clean_reply,
        'end_call': do_endcall
    })
 
# ═══════════════════════════════════════════════════════════════════════════
# SARVAM API HELPERS
# ═══════════════════════════════════════════════════════════════════════════
async def sarvam_stt(audio_bytes: bytes) -> str:
    if not audio_bytes:
        return ''
    async with aiohttp.ClientSession() as s:
        form = aiohttp.FormData()
        form.add_field('file', audio_bytes, filename='audio.wav', content_type='audio/wav')
        form.add_field('language_code', 'unknown')  # auto-detect language
        resp = await s.post(
            'https://api.sarvam.ai/speech-to-text',
            headers={'api-subscription-key': SARVAM_KEY},
            data=form
        )
        result = await resp.json()
        return result.get('transcript', '')
 
async def sarvam_chat(messages: list) -> str:
    async with aiohttp.ClientSession() as s:
        resp = await s.post(
            'https://api.sarvam.ai/v1/chat/completions',
            headers={'api-subscription-key': SARVAM_KEY,
                     'Content-Type': 'application/json'},
            json={'model': 'sarvam-m', 'messages': messages,
                  'max_tokens': 120, 'temperature': 0.7}
        )
        data = await resp.json()
        return data['choices'][0]['message']['content'].strip()
 
async def sarvam_tts(text: str, lang: str = 'hi-IN') -> str:
    async with aiohttp.ClientSession() as s:
        resp = await s.post(
            'https://api.sarvam.ai/text-to-speech',
            headers={'api-subscription-key': SARVAM_KEY,
                     'Content-Type': 'application/json'},
            json={'target_language_code': lang, 'text': text,
                  'speaker': 'meera', 'pace': 0.95, 'loudness': 1.5}
        )
        data = await resp.json()
        return data.get('audios', [''])[0]  # base64 encoded audio
 
# ═══════════════════════════════════════════════════════════════════════════
# KNOWLARITY HELPERS
# ═══════════════════════════════════════════════════════════════════════════
async def transfer_to_agent(call_id: str):
    await asyncio.sleep(3)  # let TTS finish playing
    async with aiohttp.ClientSession() as s:
        await s.post(
            'https://kpi.knowlarity.com/Basic/v1/account/call/transfer',
            headers={'x-api-key': KNOW_API_KEY, 'Authorization': KNOW_AUTH},
            json={'call_id': call_id, 'transfer_to': AGENT_EXT}
        )
    print(f'[{call_id}] Transferred to agent ext {AGENT_EXT}')
 
# ═══════════════════════════════════════════════════════════════════════════
# CALL OUTCOME LOGGING
# ═══════════════════════════════════════════════════════════════════════════
async def log_call_outcome(call_id: str, phone: str, data: dict):
    duration = data.get('call_duration', 0)
    history  = conversations.get(call_id, [])
    full_transcript = ' | '.join(
        f"{m['role']}: {m['content']}"
        for m in history if m['role'] != 'system'
    )
 
    hot_words  = ['interested','visit','site','haan','buy','kharidna','booking']
    warm_words = ['later','sochta','think','mahine','baad mein']
    if any(w in full_transcript.lower() for w in hot_words):
        status = 'HOT'
    elif any(w in full_transcript.lower() for w in warm_words):
        status = 'WARM'
    elif int(duration) < 15:
        status = 'NOT_ANSWERED'
    else:
        status = 'COLD'
 
    print(f'OUTCOME | {phone} | {status} | {duration}s')
    # Optionally log to Google Sheets here (see Section 7)
