# Türk TV Playlist

Mi Box / Android TV / Sparkle TV için ücretsiz ve açık Türk TV yayınlarından oluşturulan temiz M3U listesi.

## Kullanılacak URL'ler

Tüm seçili kanallar:
https://raw.githubusercontent.com/fatihkartl/turk-tv-playlist/main/turkiye_temiz.m3u

Yalnızca 1080p ve üzeri:
https://raw.githubusercontent.com/fatihkartl/turk-tv-playlist/main/turkiye_fhd_auto.m3u

Liste GitHub Actions tarafından 6 saatte bir güncellenir. Kaynak olarak iptv-org Türkiye akışları kullanılır; yalnızca channels.json içindeki whitelist kanallar ve güvenilir CDN alan adları kabul edilir. Ücretli/şifreli kanal kaynakları bilerek dahil edilmez.

Not: Yayıncılar CDN adresi veya erişim politikasını değiştirebilir. NOW ve Star gibi bazı kanallar kaynakta şu an 720p olabilir; FHD listesine yalnızca 1080p+ olarak bilinen akışlar girer.


## EPG / Program Rehberi

XMLTV:
https://raw.githubusercontent.com/fatihkartl/turk-tv-playlist/main/epg_turkiye.xml

Sparkle TV'de playlist EPG'yi otomatik algılamazsa bu adresi ayrıca EPG/XMLTV kaynağı olarak ekleyin.
EPG, playlist ile aynı tvg-id değerlerine yeniden eşlenir ve workflow tarafından 6 saatte bir güncellenir.


## Kanal Logoları

Playlist üreticisi iptv-org'un güncel logo API'sini kullanır:
https://iptv-org.github.io/api/logos.json

Her kanal için yalnızca aktif (in_use) logolar değerlendirilir. Ana kanal logosu tercih edilir;
uyumluluk için PNG/WebP/JPEG biçimleri SVG'nin önüne alınır. Seçilen URL M3U içindeki `tvg-logo`
alanına yazılır. Logo API geçici olarak erişilemezse mevcut playlist'teki eski logo korunur.

## Yayın Sağlık Kontrolü

Yeni veya değişmiş bir yayın URL'si doğrudan listeye alınmaz.

Güncelleme sırasında:
1. M3U8 playlist gerçekten indirilir ve `#EXTM3U` doğrulanır.
2. Master playlist ise en yüksek kaliteli varyant playlist de açılır.
3. Media playlist içinden gerçek bir video/LL-HLS segmentine erişim denenir.
4. Kontrol iki kez denenir.
5. Yeni URL doğrulanamazsa o URL'ye geçilmez; repo'daki önceki URL aynen korunur.
6. Daha önce listede olmayan bir kanalın hiçbir URL'si doğrulanamazsa kanal eklenmez.
7. Sonuçlar `health_report.json` dosyasına yazılır.

Bu yaklaşım GitHub runner'ın Türkiye dışında olması nedeniyle geo-block'lu bir yayını yanlış negatif
görmesi durumunda da listeyi gereksiz yere bozmaz: doğrulanamayan yeni linke geçmek yerine önceki
link korunur.

## Otomasyon

Workflow 6 saatte bir ve ilgili yapılandırma/script dosyaları değiştiğinde çalışacak şekilde ayarlıdır.
GitHub Actions'ın repo için etkin olması gerekir. Workflow ayrıca Python syntax kontrolünü playlist
üretiminden önce yapar.
