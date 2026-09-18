"""
Colaberry student contact list.

Each student has:
- name: Full name
- personal_email: Where to send notifications
- phone: WhatsApp number
- assigned_to: Assistant name (Karthik or Vivek)
- assistant_email: Assistant's Colaberry email

CC on every notification: mika@colaberry.com, jackie@colaberry.com
"""

STUDENTS = [
    {"name": "Sarbjit Kaur",           "personal_email": "Sarbjitsaini83@yahoo.com",        "phone": "2093284394",  "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Ephrem Gebregziabher",   "personal_email": "eyohannes5@gmail.com",             "phone": "651-235-8973","assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Terri Mark",             "personal_email": "terrlmark75@gmail.com",             "phone": "(936)-366-8606","assigned_to": "Karthik","assistant_email": "karthik@colaberry.com"},
    {"name": "Yannick Patrick Ntwari", "personal_email": "Yannickntwari8@gmail.com",          "phone": "207-329-5205","assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Aisha Hobbs",            "personal_email": "msajhobbs@gmail.com",               "phone": "972-896-0419","assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Mequanint Kiflu",        "personal_email": "muhatmender@gmail.com",             "phone": "214-861-9744","assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Kesetebirhan Yirdaw",    "personal_email": "kesetebirhan@gmail.com",            "phone": "15714782790","assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Betty",                  "personal_email": "bettykerubo24@gmail.com",           "phone": "5855196051", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Jeanne Uwimpuhwe",       "personal_email": "j.uwimpuhwe07@gmail.com",           "phone": "8174807253", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Eyerusalem Sahle",       "personal_email": "eyerutigistu@gmail.com",            "phone": "571-447-2696","assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Hemambika Ilangovan",    "personal_email": "hemailango@gmail.com",              "phone": "404-921-7936","assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Siddhatapa Mohapatra",   "personal_email": "s.mohapatra2810@gmail.com",         "phone": "612-413-8955","assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Kwadjossan Isaac",       "personal_email": "kwadjossanisaackpakpavi@gmail.com", "phone": "2404869244", "assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Osarumwense Aghimien",   "personal_email": "osadynasty12@gmail.com",            "phone": "404-563-0074","assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Senayit Berhane",        "personal_email": "berhanesenayit@gmail.com",          "phone": "3607288051", "assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Rutendo Bwerazuva",      "personal_email": "rbwerazuva@gmail.com",              "phone": "817-374-7504","assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Allan Smith Njeri",      "personal_email": "smithkariuki258@gmail.com",         "phone": "9133131870", "assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Abdulheli Mukunzi",      "personal_email": "abdulhelimukunzi@gmail.com",        "phone": "2073310181", "assigned_to": "Vivek",   "assistant_email": "vivek@colaberry.com"},
    {"name": "Avworo", "personal_email": "", "phone": "", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Fabrice", "personal_email": "", "phone": "", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Emmanuel", "personal_email": "", "phone": "", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Promise", "personal_email": "", "phone": "", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Shylaja", "personal_email": "", "phone": "", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
    {"name": "Pandey", "personal_email": "", "phone": "", "assigned_to": "Karthik", "assistant_email": "karthik@colaberry.com"},
]

# Always CC on every notification
CC_EMAILS = ["mika@colaberry.com", "jackie@colaberry.com"]
