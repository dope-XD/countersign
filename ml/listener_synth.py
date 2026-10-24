"""Our own template calls for the scam classifier's train and dev splits (source "team_synth"): hard harmless calls
the public sets lack (a real bank's fraud alert, a police verification, a delivery OTP at the door, family talking
about scams) and Indian scams in Devanagari, as a phone's speech-to-text writes Hindi.

    python -m ml.listener_synth        # print a few

Seeded, so the same rows come out every time. Never used as a test set: the held-out sets are the public test
splits, our hand-written team_calls and data/listener/adversarial.jsonl, which were written separately.
"""

from __future__ import annotations

import random

BANKS = ["SBI", "HDFC Bank", "ICICI Bank", "Axis Bank", "Bank of Baroda", "Canara Bank", "PNB", "Kotak"]
NAMES = ["Sharma", "Verma", "Iyer", "Khan", "Patel", "Reddy", "Singh", "Das", "Nair", "Gupta"]
FIRST = ["Rahul", "Priya", "Amit", "Neha", "Suresh", "Pooja", "Vikram", "Anjali"]
SHOPS = ["Amazon", "Flipkart", "Blue Dart", "Delhivery", "Swiggy", "Zomato", "BigBasket", "Meesho"]
CITIES = ["Delhi", "Mumbai", "Pune", "Lucknow", "Jaipur", "Chennai", "Kolkata", "Indore"]

HARMLESS = {
    "en": [
        "Hello, this is {bank}'s fraud team. We declined a card payment of {amt} rupees a few minutes ago. If it was you, just try again. If not, your card is already blocked and you can get a new one at the branch. We never ask for your PIN, OTP or passwords.",
        "Good morning, I'm calling from the {bank} {city} branch about your fixed deposit. It matures next week. Please visit the branch with your passbook if you want to renew it, or do it yourself in the bank's own app.",
        "Hi, I'm the {shop} delivery partner. I'm downstairs with your order. It's cash on delivery, {amt} rupees. Can you come down, or should I come up to the {n} floor?",
        "Hello, {shop} delivery here. I'm at your door. Please tell me the delivery OTP that {shop} sent you, so I can mark the order delivered.",
        "This is Sub Inspector {name} from the {city} police station. Your passport verification is pending. Please come to the station tomorrow morning with your Aadhaar and address proof. Nothing is needed on the phone.",
        "Hello, constable {name} speaking from the local police station. We found a wallet with your driving licence in it. You can collect it from the station any time before eight in the evening.",
        "Mummy, did you hear what happened to {first}'s father? Someone called pretending to be from the police and the CBI and took two lakh rupees from him. If anyone ever calls you like that, just hang up and call me.",
        "Papa, remember: if someone says your KYC has expired or your account is blocked and asks for an OTP, it's a scam. The bank never asks for an OTP on a call. Cut the call and phone me.",
        "Hello, Dr {name}'s clinic here. Your appointment is tomorrow at {h} o'clock. Please bring your old reports and come on an empty stomach for the blood test.",
        "Hi Ma, it's {first}. My college fees are due on Friday. Papa said he'd send it, can you remind him tonight? No rush. How is your knee now?",
        "Hello sir, I'm calling from {bank} about the home loan you applied for. We need your salary slips and PAN card at the branch. No payment is taken on the phone.",
        "Hello, this is the electricity office. Power will be off in your area tomorrow from {h} to {h2} for repairs. You don't need to do anything.",
        "Hi, this is the school office. The parent teacher meeting is on Saturday at {h}. Please also pay the term fee at the school counter or on the school's own website before the {n}th.",
        "Hello, LIC branch office here. Your premium of {amt} rupees is due this month. You can pay at the branch or in the LIC app. There's no penalty in the grace period.",
        "Hello, Airtel customer care calling back about your complaint. Our technician will come tomorrow between {h} and {h2}. He won't ask for any money.",
        "Bhaiya, I saw on the news that people are getting fake calls about parcels with drugs from customs. Tell Dadi not to believe anyone who says that, and never to send money.",
        "Hello, I'm calling from the society office. The water tank cleaning is on Sunday, so there'll be no water from {h} to {h2}. Please store some water.",
        "Hi, it's {first} from your office. The meeting moved to {h} tomorrow. Can you send me the sales report before that?",
    ],
    "hinglish": [
        "Namaste, main {bank} ki fraud team se bol rahi hoon. Aapke card se {amt} rupaye ka payment humne rok diya hai. Agar aapne kiya tha to dobara try kijiye, warna card block hai, naya card branch se le lijiye. Hum kabhi PIN ya OTP nahi poochte.",
        "Hello sir, {bank} {city} branch se bol raha hoon. Aapka FD agle hafte mature ho raha hai. Renew karna ho to passbook lekar branch aa jaiye.",
        "Hello madam, {shop} se delivery hai. Main neeche khada hoon. Cash on delivery hai, {amt} rupaye. Aap neeche aayengi ya main upar aa jaun?",
        "Bhaiya {shop} delivery, main darwaze pe hoon. {shop} ne jo OTP bheja hai woh bata dijiye, order deliver mark karna hai.",
        "Namaste ji, {city} thane se sub inspector {name} bol raha hoon. Aapke passport ki verification baaki hai. Kal subah Aadhaar aur address proof lekar thane aa jaiye. Phone pe kuch nahi chahiye.",
        "Mummy aapne suna? {first} ke papa ko kisi ne nakli police banke phone kiya aur do lakh le liye. Koi bhi aisa phone kare to turant kaat dena aur mujhe call karna.",
        "Papa yaad rakhna, koi bole KYC expire ho gaya ya account block ho jayega aur OTP maange, to woh fraud hai. Bank kabhi call pe OTP nahi maangta. Phone kaat ke mujhe call karna.",
        "Hello, Dr {name} ke clinic se bol rahe hain. Kal {h} baje aapka appointment hai. Purani reports le aaiye aur khali pet aaiye blood test ke liye.",
        "Haan Ma main {first}. Friday ko college ki fees deni hai, papa ne kaha tha bhej denge, aap unko yaad dila dena. Koi jaldi nahi. Aapka ghutna kaisa hai ab?",
        "Hello sir, {bank} se home loan ke baare mein call kiya. Salary slip aur PAN card branch mein jama karne honge. Phone pe koi payment nahi hoti.",
        "Namaste, bijli office se. Kal {h} se {h2} baje tak aapke area mein bijli band rahegi, repair ka kaam hai. Aapko kuch nahi karna.",
        "Hello, LIC branch se bol rahe hain. Aapka {amt} rupaye ka premium is mahine due hai. Branch mein ya LIC app mein bhar dijiye.",
        "Bhai news dekhi? Log customs ke naam pe nakli call kar rahe hain ki parcel mein drugs hain. Dadi ko bata dena kisi ki baat na maanein aur paise kabhi na bhejein.",
        "Hello, society office se. Sunday ko tanki saaf hogi, {h} se {h2} baje tak paani nahi aayega. Thoda paani bhar ke rakh lijiye.",
        "Hello ji, Airtel customer care se. Aapki complaint ke liye technician kal {h} se {h2} ke beech aayega. Woh koi paisa nahi maangega.",
    ],
    "hi": [
        "नमस्ते, मैं {bank} की फ्रॉड टीम से बोल रही हूँ। आपके कार्ड से {amt} रुपये का पेमेंट हमने रोक दिया है। अगर आपने किया था तो दोबारा कीजिए, वरना कार्ड बंद है, नया कार्ड शाखा से ले लीजिए। हम कभी पिन या ओटीपी नहीं पूछते।",
        "नमस्ते जी, {city} थाने से सब इंस्पेक्टर {name} बोल रहा हूँ। आपके पासपोर्ट का वेरिफिकेशन बाकी है। कल सुबह आधार और पते का सबूत लेकर थाने आ जाइए। फ़ोन पर कुछ नहीं चाहिए।",
        "मम्मी, आपने सुना? {first} के पापा को किसी ने नकली पुलिस बनकर फ़ोन किया और दो लाख रुपये ले लिए। कोई भी ऐसा फ़ोन करे तो तुरंत काट देना और मुझे फ़ोन करना।",
        "पापा याद रखना, कोई कहे कि केवाईसी खत्म हो गया या खाता बंद हो जाएगा और ओटीपी माँगे, तो वो धोखा है। बैंक कभी फ़ोन पर ओटीपी नहीं माँगता।",
        "नमस्ते, डॉक्टर {name} के क्लिनिक से बोल रहे हैं। कल {h} बजे आपका अपॉइंटमेंट है। पुरानी रिपोर्ट ले आइए और खाली पेट आइए।",
        "हाँ माँ, मैं {first}। शुक्रवार को कॉलेज की फीस देनी है, पापा ने कहा था भेज देंगे, आप उन्हें याद दिला देना। कोई जल्दी नहीं।",
        "नमस्ते, बिजली दफ़्तर से। कल {h} से {h2} बजे तक आपके इलाके में बिजली बंद रहेगी। आपको कुछ नहीं करना है।",
        "मैडम, {shop} से डिलीवरी है। मैं नीचे खड़ा हूँ। कैश ऑन डिलीवरी है, {amt} रुपये। आप नीचे आएँगी या मैं ऊपर आ जाऊँ?",
        "नमस्ते सर, {bank} की {city} शाखा से बोल रहा हूँ। आपकी एफडी अगले हफ़्ते पूरी हो रही है। नया करवाना हो तो पासबुक लेकर शाखा आ जाइए।",
        "भैया, खबर देखी? लोग कस्टम के नाम पर नकली फ़ोन कर रहे हैं कि पार्सल में ड्रग्स हैं। दादी को बता देना किसी की बात न मानें और कभी पैसे न भेजें।",
    ],
}

SCAMS = {
    "hi": [
        (
            "digital_arrest",
            "मैं {city} पुलिस से इंस्पेक्टर {name} बोल रहा हूँ। आपके आधार से जुड़े खाते में मनी लॉन्ड्रिंग का केस दर्ज हुआ है। आपका गिरफ्तारी वारंट निकला है। वीडियो कॉल पर रहिए और किसी को मत बताइए। जाँच के लिए अपने पैसे सुरक्षित खाते में भेज दीजिए।",
        ),
        (
            "bank_kyc",
            "नमस्ते, मैं {bank} से बोल रहा हूँ। आपका केवाईसी अपडेट नहीं है, आज रात आपका खाता बंद हो जाएगा। आपके फ़ोन पर एक ओटीपी आया है, वो बता दीजिए, मैं अभी अपडेट कर देता हूँ।",
        ),
        ("remote_access", "सर, मैं {bank} कस्टमर केयर से बोल रहा हूँ। आपके खाते से गलत पैसा कटा है, वापस करने के लिए एनीडेस्क ऐप डाउनलोड कीजिए और जो कोड आए वो मुझे बताइए।"),
        (
            "courier_customs",
            "नमस्ते, {shop} कूरियर से बोल रहे हैं। आपके नाम का पार्सल कस्टम ने पकड़ा है, उसमें ड्रग्स और पाँच पासपोर्ट मिले हैं। मैं आपको नारकोटिक्स अफ़सर से जोड़ रहा हूँ। जुर्माना अभी भरना होगा।",
        ),
        ("trai_sim", "यह ट्राई से कॉल है। आपके नंबर पर गैरकानूनी गतिविधि की शिकायत है, दो घंटे में आपकी सिम बंद हो जाएगी। बचने के लिए एक दबाएँ और पुलिस अफ़सर से बात करें।"),
        (
            "family_emergency",
            "आंटी, मैं {first} का दोस्त बोल रहा हूँ। {first} का एक्सीडेंट हो गया है, अस्पताल वाले अभी पचास हज़ार माँग रहे हैं। उसका फ़ोन टूट गया है। जल्दी इस नंबर पर यूपीआई कर दीजिए, घर पर किसी को मत बताइए।",
        ),
        ("reward", "बधाई हो! कौन बनेगा करोड़पति की लॉटरी में आपका नंबर आया है, आपने पच्चीस लाख जीते हैं। बस प्रोसेसिंग फीस के {amt} रुपये भेज दीजिए, पूरा पैसा आपके खाते में आ जाएगा।"),
        (
            "job_task",
            "घर बैठे पार्ट टाइम काम है। बस वीडियो लाइक कीजिए, हर टास्क के पैसे मिलेंगे। पहले {amt} रुपये जमा कीजिए ताकि खाता चालू हो जाए, बाद में कमीशन के साथ वापस मिलेगा।",
        ),
        ("investment", "हमारे शेयर ग्रुप में लोगों का पैसा तीन हफ़्ते में दोगुना हुआ है। आप बस हमारे पार्टनर खाते में पचास हज़ार भेजिए, मुनाफ़े की गारंटी है। आज रात तक फ़ैसला कीजिए।"),
        ("otp_upi", "मैडम, आपके खाते में गलती से {amt} रुपये आ गए हैं। मैंने आपको यूपीआई पर रिक्वेस्ट भेजी है, पिन डालकर वापस कर दीजिए, जल्दी कीजिए।"),
    ],
    "hinglish": [
        (
            "digital_arrest",
            "Main {city} police se inspector {name} bol raha hoon. Aapke Aadhaar se juda account money laundering case mein hai. Aapka arrest warrant nikla hai. Video call pe rahiye, kisi ko mat bataiye, aur verification ke liye paisa safe account mein bhejiye.",
        ),
        (
            "remote_access",
            "Sir main {bank} customer care se. Aapke account se galat paisa kata hai, refund ke liye AnyDesk download kijiye aur jo code aaye woh bataiye.",
        ),
        (
            "electricity",
            "Aapka bijli ka bill pending hai, aaj raat 9 baje connection kaat diya jayega. Abhi is number pe call karke {amt} rupaye bhariye, warna line kat jayegi.",
        ),
        (
            "otp_upi",
            "Madam galti se aapke account mein {amt} rupaye aa gaye hain. Maine UPI request bheji hai, PIN daal ke wapas kar dijiye, jaldi kijiye please.",
        ),
    ],
    "en": [
        (
            "electricity",
            "Dear customer, your electricity connection will be cut tonight at nine because last month's bill was not updated. Call our officer immediately and pay {amt} rupees to keep the power on.",
        ),
        (
            "otp_upi",
            "Madam, {amt} rupees came to your account by mistake. I've sent you a UPI request, please enter your PIN to return it quickly, it's very urgent for me.",
        ),
        (
            "digital_arrest",
            "This is officer {name} from the {city} cyber crime cell. Your Aadhaar is linked to a money laundering case. You are under digital arrest. Stay on the video call, tell no one, and transfer your savings to the verification account.",
        ),
    ],
}


def _fill(t: str, rng: random.Random) -> str:
    h = rng.randint(7, 11)
    return t.format(
        bank=rng.choice(BANKS), name=rng.choice(NAMES), first=rng.choice(FIRST), shop=rng.choice(SHOPS), city=rng.choice(CITIES),
        amt=rng.choice([499, 1200, 2999, 4500, 9999, 15000, 25000]), n=rng.randint(2, 12), h=h, h2=h + rng.randint(2, 4),
    )  # fmt: skip


def rows(per_template: int = 6, seed: int = 7) -> list[dict]:
    """Template calls, split 80/20 into train/dev by template, so dev has templates train never saw."""
    rng = random.Random(seed)
    out = []
    items = [(lang, 0, "none", t) for lang, ts in HARMLESS.items() for t in ts] + [(lang, 1, typ, t) for lang, ts in SCAMS.items() for typ, t in ts]
    for k, (lang, label, typ, t) in enumerate(items):
        split = "dev" if rng.random() < 0.2 else "train"
        for i in range(per_template):
            out.append({"id": f"team_synth/{k}/{i}", "text": _fill(t, rng), "label": label, "source": "team_synth", "lang": lang, "type": typ, "split": split})
    return out


if __name__ == "__main__":
    for r in rows()[::37]:
        print(r["split"], r["label"], r["lang"], r["text"][:100])
