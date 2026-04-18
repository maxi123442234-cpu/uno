const socket = io();

// DOM Elements
const screens = {
    auth: document.getElementById('authScreen'),
    lobby: document.getElementById('lobby'),
    game: document.getElementById('gameScreen')
};

const inputs = {
    authUsername: document.getElementById('authUsername'),
    authPass: document.getElementById('authPassword'),
    room: document.getElementById('roomName'),
    chat: document.getElementById('chatInput')
};

const btns = {
    login: document.getElementById('loginBtn'),
    register: document.getElementById('registerBtn'),
    join: document.getElementById('joinBtn'),
    send: document.getElementById('sendBtn'),
    start: document.getElementById('startBtn'),
    chatToggle: document.getElementById('chatToggleBtn'),
    closeChat: document.getElementById('closeChatBtn')
};

const ui = {
    authMsg: document.getElementById('authMsg'),
    loggedInUser: document.getElementById('loggedInUser'),
    opponents: document.getElementById('opponents'),
    hand: document.getElementById('player-hand'),
    discardPile: document.getElementById('discard-pile'),
    drawPile: document.getElementById('draw-pile'),
    chatArea: document.getElementById('chat-area'),
    chatMessages: document.getElementById('chat-messages'),
    colorPicker: document.getElementById('color-picker'),
    statusText: document.getElementById('status-text'),
    statusPanel: document.getElementById('status-panel')
};

// State
let myId = null;
let myName = null;
let currentRoom = null;
let pendingWildCardIndex = null;
let gameState = null;

// Mobile Chat Toggle
btns.chatToggle.addEventListener('click', () => ui.chatArea.classList.add('open'));
btns.closeChat.addEventListener('click', () => ui.chatArea.classList.remove('open'));

// Auth Logic
async function handleAuth(url) {
    const username = inputs.authUsername.value.trim();
    const password = inputs.authPass.value.trim();
    
    if(!username || !password) {
        ui.authMsg.innerText = "Ma'lumotlarni to'ldiring";
        return;
    }
    
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });
        const data = await res.json();
        
        if(data.success && url === '/login') {
            myName = data.username;
            ui.loggedInUser.innerText = myName;
            screens.auth.classList.remove('active');
            screens.lobby.classList.add('active');
        } else {
            ui.authMsg.innerText = data.msg;
        }
    } catch(err) {
        ui.authMsg.innerText = "Xatolik yuz berdi";
    }
}

btns.login.addEventListener('click', () => handleAuth('/login'));
btns.register.addEventListener('click', () => handleAuth('/register'));


// Game Event Listeners
btns.join.addEventListener('click', () => {
    const room = inputs.room.value.trim();
    if(room) {
        currentRoom = room;
        socket.emit('join_room', { name: myName, room });
        screens.lobby.classList.remove('active');
        screens.game.classList.add('active');
    }
});

function sendChat() {
    const msg = inputs.chat.value.trim();
    if(msg && currentRoom) {
        socket.emit('chat_message', { room: currentRoom, msg });
        inputs.chat.value = '';
    }
}
btns.send.addEventListener('click', sendChat);
inputs.chat.addEventListener('keypress', (e) => { if(e.key === 'Enter') sendChat() });

btns.start.addEventListener('click', () => {
    socket.emit('start_game', { room: currentRoom });
});

ui.drawPile.addEventListener('click', () => {
    if(isMyTurn()) socket.emit('draw_card', { room: currentRoom });
});

document.querySelectorAll('.color-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const color = e.target.getAttribute('data-color');
        ui.colorPicker.classList.add('hidden');
        if(pendingWildCardIndex !== null) {
            socket.emit('play_card', {
                room: currentRoom,
                card_index: pendingWildCardIndex,
                chosen_color: color
            });
            pendingWildCardIndex = null;
        }
    });
});

// Helpers
function isMyTurn() {
    return gameState && gameState.current_turn_id === myId;
}

function getCardVal(value) {
    if(value === 'skip') return '⊘';
    if(value === 'reverse') return '⇄';
    if(value === 'wild') return 'W';
    return value;
}

function renderUnoCard(cardDiv, cardObj, isNew = false) {
    cardDiv.className = `uno-card ${cardObj.color || 'black'} ${isNew ? 'card-entering' : ''}`;
    const valStr = getCardVal(cardObj.value);
    
    cardDiv.innerHTML = `
        <div class="inner">
            <span class="corner top-left">${valStr}</span>
            <span class="center-val">${valStr}</span>
            <span class="corner bottom-right">${valStr}</span>
        </div>
    `;
}

// Socket Events
socket.on('chat_message', (data) => {
    const div = document.createElement('div');
    div.className = 'chat-msg';
    div.innerHTML = `<b>${data.sender}:</b> ${data.msg}`;
    ui.chatMessages.appendChild(div);
    ui.chatMessages.scrollTop = ui.chatMessages.scrollHeight;
});

let lastHandSize = 0;

socket.on('game_state', (state) => {
    gameState = state;
    myId = state.my_id;

    // Upd Opponents
    ui.opponents.innerHTML = '';
    state.opponents.forEach(opp => {
        const div = document.createElement('div');
        div.className = `opponent ${state.current_turn_id === opp.id ? 'active-turn' : ''}`;
        div.innerHTML = `
            <div class="opp-name">${opp.name}</div>
            <div class="opp-cards">${opp.card_count} karta</div>
        `;
        ui.opponents.appendChild(div);
    });

    // Start Btn
    if(state.is_host && state.status === 'waiting') {
        btns.start.classList.remove('hidden');
    } else {
        btns.start.classList.add('hidden');
    }

    // Status
    let statusMsg = "";
    if(state.status === 'waiting') {
        statusMsg = "O'yinchilar kutilmoqda...";
        ui.statusPanel.classList.remove('my-turn');
    } else if(state.status === 'finished') {
        statusMsg = "O'yin tugadi!";
        ui.statusPanel.classList.remove('my-turn');
    } else {
        if(isMyTurn()) {
            statusMsg = "Sizning navbatingiz!";
            if(state.draw_penalty > 0) statusMsg += ` (+${state.draw_penalty})`;
            ui.statusPanel.classList.add('my-turn');
        } else {
            statusMsg = "Raqib navbati...";
            ui.statusPanel.classList.remove('my-turn');
        }
    }
    ui.statusText.innerText = statusMsg;

    // Discard Pile
    if(state.pile_top) {
        const top = state.pile_top;
        renderUnoCard(ui.discardPile, { value: top.value, color: state.current_color || top.color });
    } else {
        ui.discardPile.className = 'uno-card empty';
        ui.discardPile.innerHTML = `<div class="inner"><span class="center-val">Bo'sh</span></div>`;
    }

    // My Hand
    ui.hand.innerHTML = '';
    const handSize = state.my_cards.length;
    
    state.my_cards.forEach((card, index) => {
        const div = document.createElement('div');
        
        // Fan animation variables
        const rot = (index - (handSize - 1) / 2) * 5; // -10deg to 10deg roughly
        const yOffset = Math.abs(index - (handSize - 1) / 2) * 4;
        div.style.setProperty('--rot', rot);
        div.style.setProperty('--y', yOffset);
        
        const isNew = handSize > lastHandSize && index >= lastHandSize;
        renderUnoCard(div, card, isNew);
        
        div.addEventListener('click', () => {
            if(!isMyTurn()) return;
            
            if(card.type === 'wild') {
                pendingWildCardIndex = index;
                ui.colorPicker.classList.remove('hidden');
            } else {
                socket.emit('play_card', {
                    room: currentRoom,
                    card_index: index
                });
            }
        });
        
        ui.hand.appendChild(div);
    });
    
    lastHandSize = handSize;
});

