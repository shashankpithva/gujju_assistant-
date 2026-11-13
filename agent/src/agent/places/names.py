"""Gujarati names for Gujarat's districts and talukas, and the other names people call them.

The official list (data/gujarat.csv.gz) is in English. The agent reads a district or taluka back in
Gujarati, so it sounds the way the person said it, and these names are matched too. Keys are the
list's own English names (Local Government Directory, May 2026). Villages have no Gujarati here:
the agent reads a village back in the person's own words, or spells the list's name in Gujarati
letters (transliterate.py).
"""

from __future__ import annotations

DISTRICTS: dict[str, str] = {
    "Ahmedabad": "અમદાવાદ",
    "Amreli": "અમરેલી",
    "Anand": "આણંદ",
    "Arvalli": "અરવલ્લી",
    "Banas Kantha": "બનાસકાંઠા",
    "Bharuch": "ભરૂચ",
    "Bhavnagar": "ભાવનગર",
    "Botad": "બોટાદ",
    "Chhotaudepur": "છોટાઉદેપુર",
    "Dahod": "દાહોદ",
    "Dangs": "ડાંગ",
    "Devbhumi Dwarka": "દેવભૂમિ દ્વારકા",
    "Gandhinagar": "ગાંધીનગર",
    "Gir Somnath": "ગીર સોમનાથ",
    "Jamnagar": "જામનગર",
    "Junagadh": "જૂનાગઢ",
    "Kachchh": "કચ્છ",
    "Kheda": "ખેડા",
    "Mahesana": "મહેસાણા",
    "Mahisagar": "મહીસાગર",
    "Morbi": "મોરબી",
    "Narmada": "નર્મદા",
    "Navsari": "નવસારી",
    "Panch Mahals": "પંચમહાલ",
    "Patan": "પાટણ",
    "Porbandar": "પોરબંદર",
    "Rajkot": "રાજકોટ",
    "Sabar Kantha": "સાબરકાંઠા",
    "Surat": "સુરત",
    "Surendranagar": "સુરેન્દ્રનગર",
    "Tapi": "તાપી",
    "Vadodara": "વડોદરા",
    "Valsad": "વલસાડ",
    "Vav-Tharad": "વાવ-થરાદ",
}

# Other names for a district: older spellings, and the town people name it by ("ભુજ" for Kachchh).
DISTRICT_ALIASES: dict[str, tuple[str, ...]] = {
    "Ahmedabad": ("Ahmadabad", "Amdavad", "અમદાવાદ"),
    "Arvalli": ("Aravalli", "Aravali", "અરવલી", "Modasa", "મોડાસા"),
    "Banas Kantha": ("Banaskantha", "બનાસ કાંઠા", "Palanpur", "પાલનપુર"),
    "Chhotaudepur": ("Chhota Udaipur", "Chhota Udepur", "છોટા ઉદેપુર", "છોટા ઉદયપુર"),
    "Dahod": ("Dohad", "દોહદ"),
    "Dangs": ("Dang", "The Dangs", "ડાંગ્સ", "Ahwa", "આહવા"),
    "Devbhumi Dwarka": ("Dwarka", "Devbhoomi Dwarka", "દ્વારકા", "Khambhalia", "ખંભાળિયા"),
    "Gir Somnath": ("Somnath", "Gir-Somnath", "સોમનાથ", "Veraval", "વેરાવળ"),
    "Kachchh": ("Kutch", "Kachh", "Kuchchh", "કચ્છ", "Bhuj", "ભુજ"),
    "Mahesana": ("Mehsana", "મેહસાણા"),
    "Mahisagar": ("Lunawada", "લુણાવાડા"),
    "Morbi": ("Morvi", "મોરવી"),
    "Narmada": ("Rajpipla", "રાજપીપળા"),
    "Panch Mahals": ("Panchmahal", "Panchmahals", "પંચમહાલ્સ", "Godhra", "ગોધરા"),
    "Sabar Kantha": ("Sabarkantha", "સાબર કાંઠા", "Himatnagar", "Himmatnagar", "હિંમતનગર"),
    "Tapi": ("Vyara", "વ્યારા"),
    "Vadodara": ("Baroda", "બરોડા"),
    "Vav-Tharad": ("Vav Tharad", "Tharad", "Vav", "વાવ થરાદ", "થરાદ", "વાવ"),
}

# By the list's English name. Two talukas with one name (Mahuva, Mandvi, Mangrol) are said the same.
TALUKAS: dict[str, str] = {
    # Ahmedabad
    "Asarva": "અસારવા", "Bavla": "બાવળા", "Daskroi": "દસ્ક્રોઈ", "Detroj-Rampura": "દેત્રોજ-રામપુરા",
    "Dhandhuka": "ધંધુકા", "Dholera": "ધોલેરા", "Dholka": "ધોળકા", "Ghatlodiya": "ઘાટલોડિયા",
    "Mandal": "માંડલ", "Maninagar": "મણિનગર", "Sabarmati": "સાબરમતી", "Sanand": "સાણંદ",
    "Vatva": "વટવા", "Vejalpur": "વેજલપુર", "Viramgam": "વિરમગામ",
    # Amreli
    "Amreli": "અમરેલી", "Babra": "બાબરા", "Bagasara": "બગસરા", "Dhari": "ધારી", "Jafrabad": "જાફરાબાદ",
    "Khambha": "ખાંભા", "Kunkavav Vadia": "કુંકાવાવ વડિયા", "Lathi": "લાઠી", "Lilia": "લીલીયા",
    "Rajula": "રાજુલા", "Savar Kundla": "સાવરકુંડલા",
    # Anand
    "Anand City": "આણંદ શહેર", "Anand Rural": "આણંદ ગ્રામ્ય", "Anklav": "આંકલાવ", "Borsad": "બોરસદ",
    "Khambhat": "ખંભાત", "Petlad": "પેટલાદ", "Sojitra": "સોજિત્રા", "Tarapur": "તારાપુર", "Umreth": "ઉમરેઠ",
    # Arvalli
    "Bayad": "બાયડ", "Bhiloda": "ભિલોડા", "Dhansura": "ધનસુરા", "Malpur": "માલપુર", "Meghraj": "મેઘરજ",
    "Modasa": "મોડાસા", "Sathamba": "સાઠંબા", "Shamlaji": "શામળાજી",
    # Banas Kantha
    "Amirgadh": "અમીરગઢ", "Danta": "દાંતા", "Dantiwada": "દાંતીવાડા", "Deesa": "ડીસા",
    "Deesa City": "ડીસા શહેર", "Dhanera": "ધાનેરા", "Hadad": "હડાદ", "Kankrej": "કાંકરેજ", "Ogad": "ઓગડ",
    "Palanpur": "પાલનપુર", "Palanpur City": "પાલનપુર શહેર", "Vadgam": "વડગામ",
    # Bharuch
    "Amod": "આમોદ", "Anklesvar": "અંકલેશ્વર", "Bharuch": "ભરૂચ", "Bharuch City": "ભરૂચ શહેર",
    "Hansot": "હાંસોટ", "Jambusar": "જંબુસર", "Jhagadia": "ઝઘડિયા", "Netrang": "નેત્રંગ", "Vagra": "વાગરા",
    "Valia": "વાલિયા",
    # Bhavnagar
    "Bhavnagar": "ભાવનગર", "Gariadhar": "ગારિયાધાર", "Ghogha": "ઘોઘા", "Jesar": "જેસર", "Mahuva": "મહુવા",
    "Palitana": "પાલીતાણા", "Sihor": "સિહોર", "Talaja": "તળાજા", "Umrala": "ઉમરાળા",
    "Vallabhipur": "વલ્લભીપુર",
    # Botad
    "Barwala": "બરવાળા", "Botad": "બોટાદ", "Botad City": "બોટાદ શહેર", "Gadhada": "ગઢડા", "Ranpur": "રાણપુર",
    # Chhotaudepur
    "Bodeli": "બોડેલી", "Chhota Udaipur": "છોટાઉદેપુર", "Jetpur Pavi": "જેતપુર પાવી", "Kadval": "કદવાલ",
    "Kavant": "કવાંટ", "Nasvadi": "નસવાડી", "Sankheda": "સંખેડા",
    # Dahod
    "Devgadbaria": "દેવગઢ બારિયા", "Dhanpur": "ધાનપુર", "Dohad": "દાહોદ", "Fatepura": "ફતેપુરા",
    "Garbada": "ગરબાડા", "Govindguru Limdi": "ગોવિંદ ગુરુ લીમડી", "Jhalod": "ઝાલોદ", "Limkheda": "લીમખેડા",
    "Sanjeli": "સંજેલી", "Singvad": "સિંગવડ", "Sukhsar": "સુખસર",
    # Dangs
    "Ahwa": "આહવા", "Subir": "સુબીર", "Waghai": "વઘઈ",
    # Devbhumi Dwarka
    "Bhanvad": "ભાણવડ", "Kalyanpur": "કલ્યાણપુર", "Khambhalia": "ખંભાળિયા", "Okhamandal": "ઓખામંડળ",
    # Gandhinagar
    "Dehgam": "દહેગામ", "Gandhinagar": "ગાંધીનગર", "Kalol City": "કલોલ શહેર", "Kalol Gandhinagar": "કલોલ",
    "Mansa": "માણસા",
    # Gir Somnath
    "Gir Gadhda": "ગીર ગઢડા", "Kodinar": "કોડીનાર", "Patan-Veraval": "પાટણ-વેરાવળ", "Sutrapada": "સૂત્રાપાડા",
    "Talala": "તાલાલા", "Una": "ઉના", "Veraval City": "વેરાવળ શહેર",
    # Jamnagar
    "Dhrol": "ધ્રોળ", "Jamjodhpur": "જામજોધપુર", "Jamnagar City": "જામનગર શહેર",
    "Jamnagar Rural": "જામનગર ગ્રામ્ય", "Jodiya": "જોડિયા", "Kalavad": "કાલાવડ", "Lalpur": "લાલપુર",
    # Junagadh
    "Bhesan": "ભેસાણ", "Junagadh": "જૂનાગઢ", "Junagadh City": "જૂનાગઢ શહેર", "Keshod": "કેશોદ",
    "Malia Hatina": "માળિયા હાટીના", "Manavadar": "માણાવદર", "Mangrol": "માંગરોળ", "Mendarda": "મેંદરડા",
    "Vanthali": "વંથલી", "Visavadar": "વિસાવદર",
    # Kachchh
    "Abdasa": "અબડાસા", "Anjar": "અંજાર", "Bhachau": "ભચાઉ", "Bhuj": "ભુજ", "Gandhidham": "ગાંધીધામ",
    "Lakhpat": "લખપત", "Mandvi": "માંડવી", "Mundra": "મુન્દ્રા", "Nakhatrana": "નખત્રાણા", "Rapar": "રાપર",
    # Kheda
    "Fagvel": "ફાગવેલ", "Galteshwar": "ગળતેશ્વર", "Kapadvanj": "કપડવંજ", "Kathlal": "કઠલાલ", "Kheda": "ખેડા",
    "Mahudha": "મહુધા", "Matar": "માતર", "Mehmedabad": "મહેમદાવાદ", "Nadiad": "નડિયાદ",
    "Nadiad City": "નડિયાદ શહેર", "Thasra": "ઠાસરા", "Vaso": "વસો",
    # Mahesana
    "Becharaji": "બેચરાજી", "Jotana": "જોટાણા", "Kadi": "કડી", "Kheralu": "ખેરાલુ", "Mahesana": "મહેસાણા",
    "Mahesana City": "મહેસાણા શહેર", "Satlasana": "સતલાસણા", "Unjha": "ઊંઝા", "Vadnagar": "વડનગર",
    "Vijapur": "વિજાપુર", "Visnagar": "વિસનગર",
    # Mahisagar
    "Balasinor": "બાલાસિનોર", "Godhar": "ગોધર", "Kadana": "કડાણા", "Khanpur": "ખાનપુર", "Kothmba": "કોઠંબા",
    "Lunawada": "લુણાવાડા", "Santrampur": "સંતરામપુર", "Virpur": "વીરપુર",
    # Morbi
    "Halvad": "હળવદ", "Maliya": "માળિયા", "Morbi City": "મોરબી શહેર", "Morvi": "મોરબી", "Tankara": "ટંકારા",
    "Wankaner": "વાંકાનેર",
    # Narmada
    "Chikada": "ચીકદા", "Dediapada": "ડેડિયાપાડા", "Garudeshwar": "ગરુડેશ્વર", "Nandod": "નાંદોદ",
    "Sagbara": "સાગબારા", "Tilakwada": "તિલકવાડા",
    # Navsari
    "Bansda": "વાંસદા", "Chikhli": "ચીખલી", "Gandevi": "ગણદેવી", "Jalalpore": "જલાલપોર", "Khergam": "ખેરગામ",
    "Navsari": "નવસારી",
    # Panch Mahals
    "Ghoghamba": "ઘોઘંબા", "Godhra": "ગોધરા", "Halol": "હાલોલ", "Jambughoda": "જાંબુઘોડા", "Kalol": "કાલોલ",
    "Morwa (Hadaf)": "મોરવા હડફ", "Shehera": "શહેરા",
    # Patan
    "Chanasma": "ચાણસ્મા", "Harij": "હારીજ", "Patan": "પાટણ", "Patan City": "પાટણ શહેર",
    "Radhanpur": "રાધનપુર", "Sami": "સમી", "Santalpur": "સાંતલપુર", "Saraswati": "સરસ્વતી",
    "Shankheshvar": "શંખેશ્વર", "Sidhpur": "સિદ્ધપુર",
    # Porbandar
    "Kutiyana": "કુતિયાણા", "Porabandar City": "પોરબંદર શહેર", "Porbandar": "પોરબંદર", "Ranavav": "રાણાવાવ",
    # Rajkot
    "Dhoraji": "ધોરાજી", "Gondal": "ગોંડલ", "Gondal City": "ગોંડલ શહેર", "Jamkandorna": "જામકંડોરણા",
    "Jasdan": "જસદણ", "Jetpur": "જેતપુર", "Jetpur City": "જેતપુર શહેર", "Kotda Sangani": "કોટડા સાંગાણી",
    "Lodhika": "લોધિકા", "Paddhari": "પડધરી", "Rajkot": "રાજકોટ", "Rajkot East": "રાજકોટ પૂર્વ",
    "Rajkot South": "રાજકોટ દક્ષિણ", "Rajkot West": "રાજકોટ પશ્ચિમ", "Upleta": "ઉપલેટા", "Vinchchiya": "વીંછિયા",
    # Sabar Kantha
    "Himatnagar": "હિંમતનગર", "Idar": "ઈડર", "Khedbrahma": "ખેડબ્રહ્મા", "Poshina": "પોશીના",
    "Prantij": "પ્રાંતિજ", "Talod": "તલોદ", "Vadali": "વડાલી", "Vijaynagar": "વિજયનગર",
    # Surat
    "Adajan": "અડાજણ", "Ambika": "અંબિકા", "Areth": "અરેઠ", "Bardoli": "બારડોલી", "Chorasi": "ચોર્યાસી",
    "Kamrej": "કામરેજ", "Katargam": "કતારગામ", "Majura": "મજુરા", "Olpad": "ઓલપાડ", "Palsana": "પલસાણા",
    "Puna": "પુણા", "Udhna": "ઉધના", "Umarpada": "ઉમરપાડા",
    # Surendranagar
    "Chotila": "ચોટીલા", "Chuda": "ચુડા", "Dasada": "દસાડા", "Dhrangadhra": "ધ્રાંગધ્રા", "Lakhtar": "લખતર",
    "Limbdi": "લીંબડી", "Muli": "મૂળી", "Sayla": "સાયલા", "Surendranagar City": "સુરેન્દ્રનગર શહેર",
    "Thangadh": "થાનગઢ", "Wadhwan": "વઢવાણ",
    # Tapi
    "Dolvan": "ડોલવણ", "Kukarmunda": "કુકરમુંડા", "Nizar": "નિઝર", "Songadh": "સોનગઢ", "Uchchhal": "ઉચ્છલ",
    "Ukai": "ઉકાઈ", "Valod": "વાલોડ", "Vyara": "વ્યારા",
    # Vadodara
    "Dabhoi": "ડભોઈ", "Desar": "ડેસર", "Karjan": "કરજણ", "Padra": "પાદરા", "Savli": "સાવલી", "Sinor": "શિનોર",
    "Vadodara East": "વડોદરા પૂર્વ", "Vadodara North": "વડોદરા ઉત્તર", "Vadodara Rural": "વડોદરા ગ્રામ્ય",
    "Vadodara South": "વડોદરા દક્ષિણ", "Vadodara West": "વડોદરા પશ્ચિમ", "Vaghodia": "વાઘોડિયા",
    # Valsad
    "Dharampur": "ધરમપુર", "Kaprada": "કપરાડા", "Nanapodha": "નાનાપોંઢા", "Umbergaon": "ઉમરગામ",
    "Valsad": "વલસાડ", "Vapi": "વાપી",
    # Vav-Tharad
    "Bhabhar": "ભાભર", "Deodar": "દિયોદર", "Dharnidhar": "ધરણીધર", "Lakhani": "લાખણી", "Raah": "રાહ",
    "Suigam": "સુઈગામ", "Tharad": "થરાદ", "Vav": "વાવ",
}  # fmt: skip

# Other names for a taluka: older spellings, and the town people call it by. A city split into several
# talukas (Ahmedabad, Surat, Vadodara) has no taluka of its own name: the city's name finds the city
# (gazetteer.py), not the rural taluka beside it.
TALUKA_ALIASES: dict[str, tuple[str, ...]] = {
    "Anklesvar": ("Ankleshwar",),
    "Bansda": ("Vansda", "Vasda"),
    "Chhota Udaipur": ("Chhota Udepur", "Chhotaudepur", "છોટા ઉદેપુર"),
    "Chikada": ("Chikda", "ચિકદા"),
    "Dasada": ("Patdi", "પાટડી"),
    "Deodar": ("Diyodar", "દીયોદર"),
    "Devgadbaria": ("Devgadh Baria", "Baria", "દેવગઢ બારીયા"),
    "Dohad": ("Dahod", "દોહદ"),
    "Gir Gadhda": ("Gir Gadhada", "ગીરગઢડા"),
    "Govindguru Limdi": ("Govind Guru Limdi", "Limdi", "લીમડી"),
    "Jalalpore": ("Jalalpor", "જલાલપુર"),
    "Jamkandorna": ("Jam Kandorna",),
    "Jetpur Pavi": ("Pavi Jetpur", "પાવી જેતપુર"),
    "Kadval": ("Kadwal",),
    "Kalol Gandhinagar": ("Kalol",),
    "Kothmba": ("Kothamba",),
    "Kotda Sangani": ("Kotda Sanghani", "કોટડા સાંગાણી"),
    "Kunkavav Vadia": ("Kunkavav", "Vadia", "કુંકાવાવ", "વડિયા"),
    "Malia Hatina": ("Maliya Hatina", "માળીયા હાટીના"),
    "Maliya": ("Maliya Miyana", "Malia", "માળિયા મિયાણા"),
    "Mehmedabad": ("Mahemdavad", "Mahemdabad"),
    "Morvi": ("Morbi", "મોરવી"),
    "Morwa (Hadaf)": ("Morva Hadaf", "Morwa Hadaf"),
    "Nanapodha": ("Nana Pondha", "Nanapondha"),
    "Nandod": ("Rajpipla", "રાજપીપળા"),
    "Okhamandal": ("Dwarka", "Okha", "દ્વારકા", "ઓખા"),
    "Patan-Veraval": ("Veraval", "Somnath", "વેરાવળ"),
    "Porbandar": ("Porabandar",),
    "Raah": ("Rah",),
    "Savar Kundla": ("Savarkundla", "Kundla", "કુંડલા"),
    "Shamlaji": ("Shamalaji",),
    "Sidhpur": ("Siddhpur", "સિધ્ધપુર"),
    "Umbergaon": ("Umargam", "Umargaon"),
    "Vinchchiya": ("Vinchhiya", "Vichhiya", "વિછીયા"),
    "Wadhwan": ("Vadhvan", "Vadhwan"),
}

# Towns and cities (municipalities) whose list name isn't a taluka's or a district's.
TOWNS: dict[str, str] = {
    "Ahmadabad": "અમદાવાદ", "Anand": "આણંદ", "Bantwa": "બાંટવા", "Bareja": "બારેજા",
    "Baroi": "બારોઈ", "Bhayavadar": "ભાયાવદર", "Bilimora": "બીલીમોરા", "Boriavi": "બોરીઆવી",
    "Chaklasi": "ચકલાસી", "Chalala": "ચલાલા", "Chhaya": "છાયા", "Chorvad": "ચોરવાડ", "Dahod": "દાહોદ",
    "Dakor": "ડાકોર", "Damnagar": "દામનગર", "Dudhrej": "દૂધરેજ", "Dwarka": "દ્વારકા",
    "Jamnagar": "જામનગર", "Jamraval": "જામરાવલ", "Jetpur Navagadh": "જેતપુર નવાગઢ",
    "Kadodara": "કડોદરા", "Karamsad": "કરમસદ", "Mahuva": "મહુવા", "Maliya Miyana": "માળિયા મિયાણા",
    "Mandvi": "માંડવી", "Mangrol": "માંગરોળ", "Morbi": "મોરબી", "Ode": "ઓડ", "Okha": "ઓખા",
    "Pardi": "પારડી", "Patdi": "પાટડી", "Rajpipla": "રાજપીપળા", "Saputara": "સાપુતારા",
    "Savarkundla": "સાવરકુંડલા", "Sikka": "સિક્કા", "Surat": "સુરત", "Surendranagar": "સુરેન્દ્રનગર",
    "Tarsadi": "તરસાડી", "Thara": "થરા", "Umargaon": "ઉમરગામ", "Vadodara": "વડોદરા",
    "Vallabh Vidyanagar": "વલ્લભ વિદ્યાનગર", "Veraval": "વેરાવળ", "Vijalpor": "વિજલપોર",
}  # fmt: skip

# Other names for a town: the district's other names for a city the district is named after
# (gazetteer.py adds those), and these.
TOWN_ALIASES: dict[str, tuple[str, ...]] = {
    "Ahmadabad": ("Ahmedabad", "Amdavad", "અમદાવાદ"),
    "Savarkundla": ("Savar Kundla", "Kundla", "કુંડલા"),
    "Umargaon": ("Umargam", "Umbergaon"),
    "Veraval": ("Somnath",),
}
