# Mate

Sesli asistan. iPhone konuşmayı **cihazda** metne çevirir, metni WebSocket ile sunucuya yollar; sunucu metni **VoxCPM2** ile seslendirip sesi gerçek zamanlı geri akıtır. Ses sunucuya gitmez, sadece metin gider.

```
iPhone (mate-ios)                         VPS (vox, RTX 3090)
 wake word → cihaz-içi STT (Apple / Whisper)
 ses → METİN  ───────────  ws://IP:8808/ws  ──────────►  VoxCPM2 TTS
 hoparlör ◄── pcm ses akışı ◄──────────────────────────  (gerçek zamanlı)
```

> Şu an "echo": sunucu gelen metni aynen seslendirir. İleride araya LLM girecek (STT → LLM → cevap → TTS).

## Bileşenler
- **vox/** — VoxCPM2 TTS sunucusu + gerçek zamanlı WebSocket köprüsü (FastAPI). Sözleşme: `BRIDGE_PROTOCOL.md`.
- **mate-ios/** — SwiftUI sesli istemci (cihaz-içi STT: Apple veya WhisperKit turbo; köprüden TTS).
- **intent-lab/** — niyet sınıflandırma sandbox'ı.
- **mate-core/** — Node/Python çekirdek (deneysel).

## Sunucuyu çalıştırma (vox)
NVIDIA GPU'lu bir sunucuda:
```bash
cd vox
bash deploy.sh            # Mac'ten rsync + uzak kurulum (deploy.sh içindeki HOST'u kendine göre ayarla)
```
Servis `vox-tts` (systemd) olarak **8808**'de çalışır. Kontrol:
```bash
curl http://SUNUCU_IP:8808/health      # {"status":"ok","device":"cuda",...}
```
Uçlar: `WS /ws` (gerçek zamanlı), `POST /v1/audio/speech`, `GET /v1/voices`, `GET /health`.

## Mobil uygulamayı bağlama (mate-ios)
```bash
cd mate-ios && xcodegen generate && open Mate.xcodeproj   # ⌘R ile cihaza yükle
```
Uygulamada **Ayarlar → "Realtime Bridge (WebSocket TTS)"** bölümüne sunucu adresini gir:
```
ws://SUNUCU_IP:8808/ws        # örn: ws://192.168.0.150:8808/ws
```
- Ses seçimi: aynı bölümdeki picker sunucunun `/v1/voices` listesini çeker.
- Auth açıksa (sunucuda `VOX_API_KEY`) token alanını doldur; yoksa boş bırak.

### STT motoru seçimi (Ayarlar → "Ses Motoru")
Konuşma tanıma tamamen cihazda; iki motordan biri seçilir:
- **Apple** (varsayılan, ilk açılış) — anında, indirme yok, internetsiz; Türkçesi orta.
- **Whisper (turbo)** — Türkçesi belirgin daha iyi; ilk seçimde model (~630 MB) **bir kez** iner (alttaki çubukta yüzde gösterilir), sonra cihazda kalır. İnerken geçici Apple kullanılır. Ana ekrandaki rozet o an aktif motoru gösterir.

## Nasıl çalışır (özet)
1. Wake word ("candan") ile uyanır, sustuğunda konuşma kapanır.
2. Konuşma cihazda metne çevrilir (Apple veya WhisperKit turbo — Ayarlar'dan seçilir).
3. Metin WS ile köprüye gider.
4. Sunucu VoxCPM2 ile seslendirip ses parçalarını gerçek zamanlı geri yollar; uygulama anında çalar.
