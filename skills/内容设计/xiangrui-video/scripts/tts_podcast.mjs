#!/usr/bin/env node
// 火山「播客 TTS」(service_type.10050) 单人朗读：给视频口播配音，音色=群日报播客同款。
// 一次 WebSocket 会话送入全部句子（nlp_texts 同一 speaker），逐 round 收音频，
// 每句存成 outdir/line_NNN.mp3 —— 天然按句切分，prosody 还连贯。
//
// 用法: node tts_podcast.mjs --in lines.json --outdir DIR [--speaker 音色ID]
//   lines.json: {"lines": ["句子1", "句子2", ...]}
//   凭证: 环境变量 VOLC_PODCAST_APPID / VOLC_PODCAST_TOKEN（与灯下白群播客同一对）
import fs from 'fs';
import crypto from 'crypto';
import WebSocket from 'ws';
import {
  MsgType, EventType, ReceiveMessage, WaitForEvent,
  StartConnection, StartSession, FinishSession, FinishConnection,
} from './protocols.mjs';

const ENDPOINT = 'wss://openspeech.bytedance.com/api/v3/sami/podcasttts';
const APP_KEY = 'aGjiRDfUWi';
const RESOURCE_ID = 'volc.service_type.10050';

const argv = process.argv.slice(2);
const getOpt = (n, d) => { const i = argv.indexOf(`--${n}`); return i !== -1 && argv[i + 1] ? argv[i + 1] : d; };
const inFile = getOpt('in');
const outDir = getOpt('outdir');
const speaker = getOpt('speaker', process.env.VOLC_PODCAST_SPEAKER1 || 'zh_male_dayixiansheng_v2_saturn_bigtts');
const appid = process.env.VOLC_PODCAST_APPID;
const token = process.env.VOLC_PODCAST_TOKEN;

if (!inFile || !outDir) { console.error('用法: node tts_podcast.mjs --in lines.json --outdir DIR'); process.exit(1); }
if (!appid || !token) { console.error('✘ 缺凭证: VOLC_PODCAST_APPID / VOLC_PODCAST_TOKEN'); process.exit(2); }

const lines = JSON.parse(fs.readFileSync(inFile, 'utf8')).lines;
fs.mkdirSync(outDir, { recursive: true });

const reqParams = {
  input_id: `xiangrui_${Date.now()}`,
  action: 3,
  use_head_music: false,
  use_tail_music: false,
  audio_config: { format: 'mp3', sample_rate: 24000, speech_rate: 0 },
  input_info: { input_url: '', return_audio_url: false, only_nlp_text: false },
  nlp_texts: lines.map((t) => ({ text: t, speaker })),
  speaker_info: { random_order: false, speakers: [speaker] },
};

const headers = {
  'X-Api-App-Id': appid,
  'X-Api-App-Key': APP_KEY,
  'X-Api-Access-Key': token,
  'X-Api-Resource-Id': RESOURCE_ID,
  'X-Api-Connect-Id': crypto.randomUUID(),
};

let lineIdx = 0, audio = [], curVoice = '';
const ws = new WebSocket(ENDPOINT, { headers, skipUTF8Validation: true });
await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });

try {
  await StartConnection(ws);
  await WaitForEvent(ws, MsgType.FullServerResponse, EventType.ConnectionStarted);
  const sid = crypto.randomUUID();
  await StartSession(ws, new TextEncoder().encode(JSON.stringify(reqParams)), sid);
  await WaitForEvent(ws, MsgType.FullServerResponse, EventType.SessionStarted);
  await FinishSession(ws, sid);

  while (true) {
    const msg = await ReceiveMessage(ws);
    if (msg.type === MsgType.AudioOnlyServer && msg.event === EventType.PodcastRoundResponse) {
      audio.push(msg.payload);
    } else if (msg.type === MsgType.Error) {
      throw new Error(new TextDecoder().decode(msg.payload));
    } else if (msg.type === MsgType.FullServerResponse) {
      if (msg.event === EventType.PodcastRoundStart) {
        const d = JSON.parse(new TextDecoder().decode(msg.payload));
        curVoice = d.speaker || 'music';
        audio = [];
      } else if (msg.event === EventType.PodcastRoundEnd) {
        if (curVoice !== 'music' && curVoice !== 'head_music' && curVoice !== 'tail_music' && audio.length) {
          const f = `${outDir}/line_${String(lineIdx).padStart(3, '0')}.mp3`;
          fs.writeFileSync(f, Buffer.concat(audio.map((u) => Buffer.from(u))));
          console.log(`line ${lineIdx}: ${f}`);
          lineIdx++;
        }
        audio = [];
      }
    }
    if (msg.event === EventType.SessionFinished) break;
  }
  await FinishConnection(ws);
  await WaitForEvent(ws, MsgType.FullServerResponse, EventType.ConnectionFinished);
} finally { ws.close(); }

if (lineIdx !== lines.length) {
  console.error(`✘ 句数不匹配: 期望 ${lines.length} 实收 ${lineIdx}`);
  process.exit(3);
}
console.log(`done: ${lineIdx} lines`);
