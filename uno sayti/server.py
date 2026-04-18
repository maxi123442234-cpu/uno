import socketio
from aiohttp import web
import random
import sqlite3
import hashlib
import json
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# --- DATABASE SETUP ---
conn = sqlite3.connect('uno.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
conn.commit()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# --- HTTP AUTH ENDPOINTS ---
async def register(request):
    data = await request.json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return web.json_response({'success': False, 'msg': 'Ism va parolni kiriting'})
    
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hash_pw(password)))
        conn.commit()
        return web.json_response({'success': True, 'msg': "Ro'yxatdan o'tdingiz!"})
    except sqlite3.IntegrityError:
        return web.json_response({'success': False, 'msg': "Bu ism band"})

async def login(request):
    data = await request.json()
    username = data.get('username')
    password = data.get('password')
    
    c.execute("SELECT password FROM users WHERE username=?", (username,))
    row = c.fetchone()
    if row and row[0] == hash_pw(password):
        return web.json_response({'success': True, 'username': username})
    return web.json_response({'success': False, 'msg': "Ism yoki parol xato"})

# --- UNO GAME LOGIC ---
COLORS = ['red', 'green', 'blue', 'yellow']
VALUES = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'skip', 'reverse', '+2']
WILD_CARDS = ['wild', '+4']

def create_deck():
    deck = []
    for color in COLORS:
        deck.append({'color': color, 'value': '0', 'type': 'normal'})
        for val in VALUES[1:]:
            deck.append({'color': color, 'value': val, 'type': 'normal' if val.isdigit() else 'action'})
            deck.append({'color': color, 'value': val, 'type': 'normal' if val.isdigit() else 'action'})
    for _ in range(4):
        deck.append({'color': 'black', 'value': 'wild', 'type': 'wild'})
        deck.append({'color': 'black', 'value': '+4', 'type': 'wild'})
    random.shuffle(deck)
    return deck

rooms = {}

def init_room(room_id):
    rooms[room_id] = {
        'players': {}, 
        'player_order': [], 
        'deck': create_deck(),
        'pile': [], 
        'current_turn_index': 0,
        'direction': 1, 
        'status': 'waiting',
        'current_color': None, 
        'draw_penalty': 0, 
        'penalty_card_value': None 
    }

def next_turn(room, skip=False):
    step = room['direction'] * (2 if skip else 1)
    room['current_turn_index'] = (room['current_turn_index'] + step) % len(room['player_order'])

def deal_cards(room, count=7):
    for sid in room['player_order']:
        for _ in range(count):
            if not room['deck']:
                recycle_pile(room)
            room['players'][sid]['cards'].append(room['deck'].pop())

def recycle_pile(room):
    top = room['pile'].pop()
    room['deck'] = room['pile']
    room['pile'] = [top]
    for card in room['deck']:
        if card['type'] == 'wild':
            card['color'] = 'black'
    random.shuffle(room['deck'])

async def broadcast_game_state(room_id):
    if room_id not in rooms: return
    room = rooms[room_id]
    
    for sid in room['player_order']:
        player_info = room['players'][sid]
        
        opponents = []
        for other_sid in room['player_order']:
            if other_sid != sid:
                opponents.append({
                    'id': other_sid,
                    'name': room['players'][other_sid]['name'],
                    'card_count': len(room['players'][other_sid]['cards'])
                })
        
        state = {
            'status': room['status'],
            'my_cards': player_info['cards'],
            'my_id': sid,
            'is_host': player_info['is_host'],
            'opponents': opponents,
            'pile_top': room['pile'][-1] if room['pile'] else None,
            'current_color': room['current_color'],
            'current_turn_id': room['player_order'][room['current_turn_index']] if len(room['player_order'])>0 else None,
            'draw_penalty': room['draw_penalty']
        }
        await sio.emit('game_state', state, to=sid)

# --- SOCKET.IO EVENTS ---
@sio.event
async def disconnect(sid):
    for room_id, room in list(rooms.items()):
        if sid in room['players']:
            name = room['players'][sid]['name']
            del room['players'][sid]
            if sid in room['player_order']:
                room['player_order'].remove(sid)
            
            await sio.emit('chat_message', {'sender': 'Tizim', 'msg': f"{name} o'yinni tark etdi."}, room=room_id)
            
            if len(room['players']) == 0:
                del rooms[room_id]
            else:
                next_host = room['player_order'][0]
                room['players'][next_host]['is_host'] = True
                await broadcast_game_state(room_id)

@sio.event
async def join_room(sid, data):
    name = data.get('name')
    room_id = data.get('room')
    
    if not name or not room_id: return
        
    sio.enter_room(sid, room_id)
    
    if room_id not in rooms:
        init_room(room_id)
        rooms[room_id]['players'][sid] = {'name': name, 'cards': [], 'is_host': True}
    else:
        rooms[room_id]['players'][sid] = {'name': name, 'cards': [], 'is_host': False}
    
    rooms[room_id]['player_order'].append(sid)
    
    await sio.emit('chat_message', {'sender': 'Tizim', 'msg': f"{name} xonaga qo'shildi."}, room=room_id)
    await broadcast_game_state(room_id)

@sio.event
async def chat_message(sid, data):
    room_id = data.get('room')
    msg = data.get('msg')
    if room_id in rooms and sid in rooms[room_id]['players']:
        name = rooms[room_id]['players'][sid]['name']
        await sio.emit('chat_message', {'sender': name, 'msg': msg}, room=room_id)

@sio.event
async def start_game(sid, data):
    room_id = data.get('room')
    if room_id not in rooms: return
    room = rooms[room_id]
    
    if room['players'][sid]['is_host'] and len(room['player_order']) > 1:
        room['status'] = 'playing'
        room['deck'] = create_deck()
        room['pile'] = []
        for pid in room['player_order']:
            room['players'][pid]['cards'] = []
        
        deal_cards(room, 7)
        
        while room['deck'][-1]['type'] != 'normal':
            random.shuffle(room['deck'])
            
        first_card = room['deck'].pop()
        room['pile'].append(first_card)
        room['current_color'] = first_card['color']
        
        room['current_turn_index'] = random.randint(0, len(room['player_order']) - 1)
        room['draw_penalty'] = 0
        room['penalty_card_value'] = None
        room['direction'] = 1
        
        await sio.emit('chat_message', {'sender': 'Tizim', 'msg': "O'yin boshlandi!"}, room=room_id)
        await broadcast_game_state(room_id)

@sio.event
async def play_card(sid, data):
    room_id = data.get('room')
    card_index = data.get('card_index')
    chosen_color = data.get('chosen_color')
    
    if room_id not in rooms: return
    room = rooms[room_id]
    if room['status'] != 'playing': return
    
    current_turn_sid = room['player_order'][room['current_turn_index']]
    if sid != current_turn_sid: return
        
    player_cards = room['players'][sid]['cards']
    if card_index < 0 or card_index >= len(player_cards): return
        
    card = player_cards[card_index]
    top_card = room['pile'][-1]
    
    valid = False
    if room['draw_penalty'] > 0:
        if card['value'] == room['penalty_card_value']:
            valid = True
        else:
            return 
    else:
        if card['type'] == 'wild':
            valid = True
        elif card['color'] == room['current_color']:
            valid = True
        elif card['value'] == top_card['value']:
            valid = True
            
    if valid:
        played_card = player_cards.pop(card_index)
        room['pile'].append(played_card)
        room['current_color'] = chosen_color if played_card['type'] == 'wild' else played_card['color']
        
        skip_next = False
        if played_card['value'] == '+2':
            room['draw_penalty'] += 2
            room['penalty_card_value'] = '+2'
        elif played_card['value'] == '+4':
            room['draw_penalty'] += 4
            room['penalty_card_value'] = '+4'
        elif played_card['value'] == 'skip':
            skip_next = True
        elif played_card['value'] == 'reverse':
            room['direction'] *= -1
            if len(room['player_order']) == 2:
                skip_next = True
        
        if len(player_cards) == 0:
            room['status'] = 'finished'
            await sio.emit('chat_message', {'sender': 'Tizim', 'msg': f"G'OLIB: {room['players'][sid]['name']} !!!"}, room=room_id)
        else:
            next_turn(room, skip=skip_next)
            
        await broadcast_game_state(room_id)

@sio.event
async def draw_card(sid, data):
    room_id = data.get('room')
    if room_id not in rooms: return
    room = rooms[room_id]
    if room['status'] != 'playing': return
    
    current_turn_sid = room['player_order'][room['current_turn_index']]
    if sid != current_turn_sid: return
        
    draw_amount = room['draw_penalty'] if room['draw_penalty'] > 0 else 1
    
    for _ in range(draw_amount):
        if not room['deck']: recycle_pile(room)
        if room['deck']:
            room['players'][sid]['cards'].append(room['deck'].pop())
            
    room['draw_penalty'] = 0
    room['penalty_card_value'] = None
    next_turn(room)
    await broadcast_game_state(room_id)


# --- HTTP SERVER MAP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

app.router.add_post('/register', register)
app.router.add_post('/login', login)
app.router.add_get('/', lambda r: web.FileResponse(os.path.join(PUBLIC_DIR, 'index.html')))
app.router.add_static('/', PUBLIC_DIR)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    logger.info(f"Server starting on port {port}")
    web.run_app(app, host='0.0.0.0', port=port)
