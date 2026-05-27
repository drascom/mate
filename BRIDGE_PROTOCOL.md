# Mate Realtime Bridge Protocol v0 (TTS-only)

Telefon (mate-ios) ↔ VPS (vox) arasında gerçek zamanlı ses akışı sözleşmesi.
Bu sürümde **beyin yok**: telefon metin gönderir, sunucu o metni VoxCPM2 ile
seslendirip ses akışını geri yollar. STT cihazda yapılır; **yukarı ses gitmez**.

## Transport

WebSocket. URL: `ws://HOST:PORT/ws`  (TLS varsa `wss://`)
Opsiyonel auth: ilk mesajda veya query string `?token=...` (VOX_API_KEY ile eşleşmeli).

## Mesaj akışı

### İstemci → Sunucu  (text frame, JSON)

```json
{"type":"speak", "id":"<uuid>", "text":"Seslendirilecek metin", "voice":"ayhan"}
{"type":"cancel","id":"<uuid>"}        // barge-in: o id'nin üretimini durdur
{"type":"ping"}
```

- `voice` opsiyonel; yoksa varsayılan ses. `voices/<voice>.wav` ile klonlama.
- `id` her konuşma isteği için istemci üretir; ses parçaları bu id ile eşleşir.

### Sunucu → İstemci

Önce kontrol mesajı (text/JSON), sonra **binary** ses parçaları, sonra bitiş:

```json
{"type":"audio_start","id":"<uuid>","sample_rate":48000,"channels":1,"format":"pcm_f32le"}
```
```
<binary frame> <binary frame> ...   // ham PCM, little-endian float32, mono, sıralı
```
```json
{"type":"audio_end","id":"<uuid>"}
{"type":"error","id":"<uuid>","message":"..."}
{"type":"pong"}
```

## Ses formatı (KESİN)

- **pcm_f32le**: little-endian 32-bit float, **mono**, `sample_rate` = modelin sr'i (48000).
- Sıkıştırma yok, WAV başlığı yok — sadece ham örnekler. LAN/Wi-Fi için bant genişliği sorun değil.
- Bu format her iki tarafta da sıfır dönüşüm sağlar:
  - Sunucu: VoxCPM2 zaten float32 numpy üretir → `.astype('<f4').tobytes()`.
  - iOS: doğrudan `AVAudioPCMBuffer` (`.pcmFormatFloat32`) `channelData`'ya yazılır.
- iOS playback engine farklı sr'de ise AudioPlayer mevcut resample yolunu kullanır.

## Davranış kuralları

- Sunucu `speak` alınca: `audio_start` → parçalar (`generate_streaming` üretir üretmez) → `audio_end`.
- Yeni `speak` veya `cancel` gelirse devam eden üretim iptal edilir (barge-in), kalan parçalar gönderilmez.
- Bağlantı kopunca üretim iptal edilir; model bellekte sıcak kalır (yeniden yüklenmez).
- GPU çağrıları bağlantı başına serialize (tek aktif üretim).

## Kapsam dışı (sonraki sürüm)

- Beyin/LLM (cevap üretimi) — şimdilik sunucu gelen metni aynen seslendirir.
- Çoklu eşzamanlı kullanıcı kuyruğu, metrik/telemetri.
