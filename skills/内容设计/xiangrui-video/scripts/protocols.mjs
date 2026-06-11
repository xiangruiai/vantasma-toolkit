// 火山引擎播客 TTS 二进制 WebSocket 协议（从官方 TS SDK demo 移植为纯 ESM）
// 原始来源：volcengine_podcasts_demo/src/protocols.ts (volc_speech_js_sdk 1.0.0.19)
// 改动：去掉 TS 类型 / 用 node 内置常量；其余 marshal/unmarshal 逻辑逐字对齐官方实现。
// 整数字段全部大端（big-endian）。

export const EventType = {
  None: 0,
  StartConnection: 1,
  FinishConnection: 2,
  ConnectionStarted: 50,
  ConnectionFailed: 51,
  ConnectionFinished: 52,
  StartSession: 100,
  CancelSession: 101,
  FinishSession: 102,
  SessionStarted: 150,
  SessionCanceled: 151,
  SessionFinished: 152,
  SessionFailed: 153,
  UsageResponse: 154,
  TaskRequest: 200,
  UpdateConfig: 201,
  AudioMuted: 250,
  SayHello: 300,
  TTSSentenceStart: 350,
  TTSSentenceEnd: 351,
  TTSResponse: 352,
  TTSEnded: 359,
  PodcastRoundStart: 360,
  PodcastRoundResponse: 361,
  PodcastRoundEnd: 362,
  PodcastEnd: 363,
};

export const MsgType = {
  Invalid: 0,
  FullClientRequest: 0b1,
  AudioOnlyClient: 0b10,
  FullServerResponse: 0b1001,
  AudioOnlyServer: 0b1011,
  FrontEndResultServer: 0b1100,
  Error: 0b1111,
};

export const MsgTypeFlagBits = {
  NoSeq: 0,
  PositiveSeq: 0b1,
  LastNoSeq: 0b10,
  NegativeSeq: 0b11,
  WithEvent: 0b100,
};

const VersionBits = { Version1: 1 };
const HeaderSizeBits = { HeaderSize4: 1 };
const SerializationBits = { Raw: 0, JSON: 0b1 };
const CompressionBits = { None: 0 };

const eventName = (e) =>
  Object.keys(EventType).find((k) => EventType[k] === e) || `invalid(${e})`;
const msgTypeName = (t) =>
  Object.keys(MsgType).find((k) => MsgType[k] === t) || `invalid(${t})`;

export function messageToString(msg) {
  const ev = msg.event !== undefined ? eventName(msg.event) : 'NoEvent';
  const ty = msgTypeName(msg.type);
  if (msg.type === MsgType.Error) {
    return `MsgType: ${ty}, EventType: ${ev}, ErrorCode: ${msg.errorCode}, Payload: ${new TextDecoder().decode(msg.payload)}`;
  }
  if (msg.type === MsgType.AudioOnlyServer || msg.type === MsgType.AudioOnlyClient) {
    return `MsgType: ${ty}, EventType: ${ev}, PayloadSize: ${msg.payload.length}`;
  }
  return `MsgType: ${ty}, EventType: ${ev}, Payload: ${new TextDecoder().decode(msg.payload)}`;
}

function createMessage(msgType, flag) {
  return {
    type: msgType,
    flag,
    version: VersionBits.Version1,
    headerSize: HeaderSizeBits.HeaderSize4,
    serialization: SerializationBits.JSON,
    compression: CompressionBits.None,
    payload: new Uint8Array(0),
    toString() {
      return messageToString(this);
    },
  };
}

function u32(n) {
  const b = new ArrayBuffer(4);
  new DataView(b).setUint32(0, n, false);
  return new Uint8Array(b);
}
function i32(n) {
  const b = new ArrayBuffer(4);
  new DataView(b).setInt32(0, n, false);
  return new Uint8Array(b);
}

export function marshalMessage(msg) {
  const buffers = [];
  const headerSize = 4 * msg.headerSize;
  const header = new Uint8Array(headerSize);
  header[0] = (msg.version << 4) | msg.headerSize;
  header[1] = (msg.type << 4) | msg.flag;
  header[2] = (msg.serialization << 4) | msg.compression;
  buffers.push(header);

  if (msg.flag === MsgTypeFlagBits.WithEvent) {
    // event
    buffers.push(i32(msg.event));
    // session id（连接级事件不带 session id）
    const noSession = [
      EventType.StartConnection,
      EventType.FinishConnection,
      EventType.ConnectionStarted,
      EventType.ConnectionFailed,
    ].includes(msg.event);
    if (!noSession) {
      const sid = Buffer.from(msg.sessionId || '', 'utf8');
      buffers.push(u32(sid.length));
      buffers.push(new Uint8Array(sid));
    }
  }

  // payload（size + body）
  buffers.push(u32(msg.payload.length));
  buffers.push(msg.payload);

  const total = buffers.reduce((s, b) => s + b.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const b of buffers) {
    out.set(b, off);
    off += b.length;
  }
  return out;
}

export function unmarshalMessage(data) {
  if (data.length < 3) throw new Error(`data too short: ${data.length}`);
  const vhs = data[0];
  const tf = data[1];
  const sc = data[2];
  const msg = {
    version: vhs >> 4,
    headerSize: vhs & 0x0f,
    type: tf >> 4,
    flag: tf & 0x0f,
    serialization: sc >> 4,
    compression: sc & 0x0f,
    payload: new Uint8Array(0),
    toString() {
      return messageToString(this);
    },
  };
  let off = 4 * msg.headerSize;
  const dv = (p, len) => new DataView(data.buffer, data.byteOffset + p, len);

  // sequence（仅带 seq flag 的音频/full 消息）
  if (
    (msg.type === MsgType.AudioOnlyServer ||
      msg.type === MsgType.FullServerResponse ||
      msg.type === MsgType.FrontEndResultServer) &&
    (msg.flag === MsgTypeFlagBits.PositiveSeq || msg.flag === MsgTypeFlagBits.NegativeSeq)
  ) {
    msg.sequence = dv(off, 4).getInt32(0, false);
    off += 4;
  }
  if (msg.type === MsgType.Error) {
    msg.errorCode = dv(off, 4).getUint32(0, false);
    off += 4;
  }

  if (msg.flag === MsgTypeFlagBits.WithEvent) {
    msg.event = dv(off, 4).getInt32(0, false);
    off += 4;
    // session id
    const noSession = [
      EventType.StartConnection,
      EventType.FinishConnection,
      EventType.ConnectionStarted,
      EventType.ConnectionFailed,
      EventType.ConnectionFinished,
    ].includes(msg.event);
    if (!noSession) {
      const size = dv(off, 4).getUint32(0, false);
      off += 4;
      if (size > 0) {
        msg.sessionId = new TextDecoder().decode(data.slice(off, off + size));
        off += size;
      }
    }
    // connect id（仅连接级响应）
    if (
      [EventType.ConnectionStarted, EventType.ConnectionFailed, EventType.ConnectionFinished].includes(
        msg.event
      )
    ) {
      const size = dv(off, 4).getUint32(0, false);
      off += 4;
      if (size > 0) {
        msg.connectId = new TextDecoder().decode(data.slice(off, off + size));
        off += size;
      }
    }
  }

  // payload
  const psize = dv(off, 4).getUint32(0, false);
  off += 4;
  if (psize > 0) {
    msg.payload = data.slice(off, off + psize);
    off += psize;
  }
  return msg;
}

// === 消息收发（基于回调队列，逐字对齐 demo 行为）===
const queues = new Map();
const callbacks = new Map();

function setup(ws) {
  if (queues.has(ws)) return;
  queues.set(ws, []);
  callbacks.set(ws, []);
  ws.on('message', (data) => {
    let u8;
    if (Buffer.isBuffer(data)) u8 = new Uint8Array(data);
    else if (data instanceof ArrayBuffer) u8 = new Uint8Array(data);
    else if (data instanceof Uint8Array) u8 = data;
    else throw new Error(`Unexpected ws message type: ${typeof data}`);
    const msg = unmarshalMessage(u8);
    const cbs = callbacks.get(ws);
    if (cbs.length > 0) cbs.shift()(msg);
    else queues.get(ws).push(msg);
  });
  ws.on('close', () => {
    queues.delete(ws);
    callbacks.delete(ws);
  });
}

export function ReceiveMessage(ws) {
  setup(ws);
  return new Promise((resolve, reject) => {
    const q = queues.get(ws);
    const cbs = callbacks.get(ws);
    if (q.length > 0) return resolve(q.shift());
    const onErr = (e) => {
      const i = cbs.indexOf(resolver);
      if (i !== -1) cbs.splice(i, 1);
      reject(e);
    };
    const resolver = (msg) => {
      ws.removeListener('error', onErr);
      resolve(msg);
    };
    cbs.push(resolver);
    ws.once('error', onErr);
  });
}

export async function WaitForEvent(ws, msgType, eventType) {
  const msg = await ReceiveMessage(ws);
  if (msg.type !== msgType || msg.event !== eventType) {
    throw new Error(
      `Unexpected message: type=${msgTypeName(msg.type)}, event=${eventName(msg.event || 0)}, payload=${new TextDecoder().decode(msg.payload)}`
    );
  }
  return msg;
}

function send(ws, msg) {
  const data = marshalMessage(msg);
  return new Promise((resolve, reject) => {
    ws.send(data, (err) => (err ? reject(err) : resolve()));
  });
}

export function StartConnection(ws) {
  const m = createMessage(MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent);
  m.event = EventType.StartConnection;
  m.payload = new TextEncoder().encode('{}');
  return send(ws, m);
}
export function FinishConnection(ws) {
  const m = createMessage(MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent);
  m.event = EventType.FinishConnection;
  m.payload = new TextEncoder().encode('{}');
  return send(ws, m);
}
export function StartSession(ws, payload, sessionId) {
  const m = createMessage(MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent);
  m.event = EventType.StartSession;
  m.sessionId = sessionId;
  m.payload = payload;
  return send(ws, m);
}
export function FinishSession(ws, sessionId) {
  const m = createMessage(MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent);
  m.event = EventType.FinishSession;
  m.sessionId = sessionId;
  m.payload = new TextEncoder().encode('{}');
  return send(ws, m);
}
