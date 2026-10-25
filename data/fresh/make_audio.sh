# Speak the fresh calls with voices the models never trained on (macOS Rishi en-IN, Lekha hi-IN): clean, and through a
# phone line (300-3400 Hz, 8 kHz, mu-law).
set -e
cd "$(dirname "$0")"
python3 -c "import json; [print(n+'\t'+l+'\t'+t) for n,_,l,t in json.load(open('source.json'))['calls']]" | while IFS=$'\t' read -r n l t; do
  v=Rishi; [ "$l" = hi ] && v=Lekha
  say -v "$v" -r 165 -o "/tmp/$n.aiff" "$t"
  ffmpeg -v error -y -i "/tmp/$n.aiff" -ar 16000 -ac 1 "clean/$n.wav"
  ffmpeg -v error -y -i "/tmp/$n.aiff" -af "highpass=f=300,lowpass=f=3400" -ar 8000 -ac 1 -c:a pcm_mulaw /tmp/$n.mulaw.wav
  ffmpeg -v error -y -i /tmp/$n.mulaw.wav -ar 16000 -c:a pcm_s16le "phone/$n.wav"
  rm -f "/tmp/$n.aiff" /tmp/$n.mulaw.wav
done
