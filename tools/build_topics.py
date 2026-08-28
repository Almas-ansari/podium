"""Generates data/topics.json. Run once; the JSON is the shipped artefact.

Each entry: id, text, age_band, category, modes.
mode code: b = both, p = prepared only, i = impromptu only.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "topics.json"

BANDS: dict[str, dict[str, list[tuple[str, str]]]] = {}

BANDS["6-8"] = {
"school": [
    ("My favourite thing about school", "b"),
    ("What I do in the school playground", "b"),
    ("My best friend at school", "b"),
    ("The best day I had at school", "b"),
    ("What I keep in my school bag", "i"),
    ("My favourite teacher and why", "b"),
    ("The game we play during lunch break", "b"),
    ("What I want to learn this year", "b"),
    ("My school uniform", "i"),
    ("The morning assembly at my school", "b"),
],
"family": [
    ("My family", "b"),
    ("What my mother does that makes me happy", "b"),
    ("A game I play with my brother or sister", "b"),
    ("My grandparents", "b"),
    ("Sunday at my house", "b"),
    ("The person in my family who makes me laugh", "b"),
    ("What we do together in the evening", "i"),
    ("My favourite family photo", "b"),
    ("Helping at home", "b"),
    ("A trip I took with my family", "b"),
],
"festivals": [
    ("Diwali at my house", "b"),
    ("My favourite festival", "b"),
    ("How we celebrate Holi", "b"),
    ("The best part of Eid", "b"),
    ("Making rangoli", "b"),
    ("Christmas and what I like about it", "b"),
    ("Raksha Bandhan with my brother or sister", "b"),
    ("The sweets we eat at festivals", "i"),
    ("New clothes for a festival", "i"),
    ("Lighting diyas", "b"),
],
"animals": [
    ("My favourite animal", "b"),
    ("If I had a pet dog", "b"),
    ("The elephant", "b"),
    ("Birds I see near my house", "b"),
    ("Why the peacock is beautiful", "b"),
    ("A cat I know", "i"),
    ("Animals at the zoo", "b"),
    ("The cow", "b"),
    ("Why we should be kind to street dogs", "b"),
    ("Fish in the sea", "b"),
],
"food": [
    ("My favourite food", "b"),
    ("The best thing my mother cooks", "b"),
    ("Mangoes", "b"),
    ("Why I like ice cream", "b"),
    ("Food I do not like", "i"),
    ("What I eat in my tiffin", "b"),
    ("Chocolate", "b"),
    ("A meal we eat on special days", "b"),
    ("Fruits are good for us", "b"),
    ("Helping in the kitchen", "i"),
],
"imagination": [
    ("If I could fly", "b"),
    ("If I had a magic pencil", "b"),
    ("A day when I become very small", "b"),
    ("My own superhero", "b"),
    ("If toys could talk", "b"),
    ("A house made of sweets", "b"),
    ("If I met an alien", "i"),
    ("The best dream I remember", "b"),
    ("If I could talk to animals", "b"),
    ("A hidden door in my school", "i"),
],
"opinions": [
    ("Homework is good or not good", "b"),
    ("Why we should not waste water", "b"),
    ("Why sharing is important", "b"),
    ("Rain is the best weather", "b"),
    ("Why we should keep our class clean", "b"),
    ("Morning is better than night", "i"),
    ("Why we should say thank you", "b"),
    ("Playing outside is better than watching TV", "b"),
],
"would-you-rather": [
    ("Would you rather have a pet lion or a pet monkey", "i"),
    ("Would you rather be very tall or very fast", "i"),
    ("Would you rather eat only sweets or only fruits", "i"),
    ("Would you rather live near the sea or in the mountains", "b"),
    ("Would you rather have summer all year or rain all year", "i"),
    ("Would you rather be able to fly or be invisible", "b"),
    ("Would you rather have a robot friend or a real puppy", "i"),
],
"my-favourite": [
    ("My favourite colour", "i"),
    ("My favourite cartoon", "b"),
    ("My favourite game", "b"),
    ("My favourite place", "b"),
    ("My favourite song", "i"),
    ("My favourite toy", "b"),
    ("My favourite season", "b"),
    ("My favourite day of the week", "i"),
    ("My favourite storybook", "b"),
],
"if-I-could": [
    ("If I could go anywhere tomorrow", "b"),
    ("If I were the teacher for one day", "b"),
    ("If I could plant a magic tree", "b"),
    ("If I could meet any cartoon character", "i"),
    ("If I could keep one wish", "b"),
    ("If I could change one rule at home", "i"),
    ("If I could ride a dinosaur", "i"),
],
}

BANDS["9-11"] = {
"school": [
    ("The best thing about my school", "b"),
    ("A subject I used to find hard and now enjoy", "b"),
    ("What makes a good teacher", "b"),
    ("Should school days be shorter", "b"),
    ("The most useful thing I have learned in school", "b"),
    ("A school trip I will not forget", "b"),
    ("Why the library matters", "b"),
    ("What I would change about my school", "b"),
    ("Sports day at my school", "b"),
    ("Being the class monitor", "i"),
    ("Group projects: good or bad", "b"),
    ("The first day at a new school", "b"),
],
"family": [
    ("Something my grandparents taught me", "b"),
    ("The person in my family I admire most", "b"),
    ("A family tradition we keep", "b"),
    ("What being an elder or younger sibling is really like", "b"),
    ("A time my family surprised me", "b"),
    ("The best advice anyone at home has given me", "b"),
    ("How my family spends a holiday", "i"),
    ("A story my parents tell about when they were young", "b"),
    ("Why family dinners matter", "b"),
    ("Looking after a younger cousin", "i"),
],
"festivals": [
    ("The Diwali I remember best", "b"),
    ("Why we celebrate Independence Day", "p"),
    ("Republic Day and what it means to me", "p"),
    ("Festivals bring people together", "b"),
    ("How my city changes during festival season", "b"),
    ("Celebrating a festival that is not my own", "b"),
    ("Why crackers should be quieter", "b"),
    ("Preparing for Ganesh Chaturthi", "b"),
    ("Onam, Pongal or Bihu: a harvest festival I know", "b"),
    ("Gandhi Jayanti", "p"),
    ("Children's Day and Pandit Nehru", "p"),
    ("Navratri nights", "b"),
],
"animals": [
    ("Why street animals need our help", "b"),
    ("The tiger and why India protects it", "p"),
    ("Should zoos exist", "b"),
    ("An animal I would like to study", "b"),
    ("My pet and what it taught me", "b"),
    ("Why bees matter more than we think", "p"),
    ("Animals are smarter than we assume", "b"),
    ("The elephant in Indian life", "p"),
    ("What I would do if I found an injured bird", "i"),
],
"food": [
    ("The best meal I have ever eaten", "b"),
    ("Street food in my city", "b"),
    ("Why wasting food is wrong", "b"),
    ("A dish from my region and how it is made", "p"),
    ("Junk food and school canteens", "b"),
    ("Cooking something for the first time", "b"),
    ("Food tastes better when you share it", "b"),
    ("Why breakfast should not be skipped", "b"),
],
"imagination": [
    ("If I woke up on another planet", "b"),
    ("A day when everyone could read minds", "b"),
    ("Inventing something my school needs", "b"),
    ("If I could travel one hundred years forward", "b"),
    ("A world without electricity for one week", "b"),
    ("The story behind an old photograph", "i"),
    ("If books came alive at night", "b"),
    ("Designing my own city", "p"),
    ("If I could speak every language", "b"),
],
"opinions": [
    ("Should children have mobile phones", "b"),
    ("Homework should be replaced with reading", "b"),
    ("Is winning the most important thing in sport", "b"),
    ("Why kindness is a skill, not a feeling", "b"),
    ("Should exams be scrapped", "b"),
    ("Screen time: who should decide", "b"),
    ("Why we should all learn to swim", "b"),
    ("Cleanliness is everyone's job, not the sweeper's", "b"),
    ("Should uniforms be compulsory", "b"),
    ("Saving water starts at home", "b"),
],
"would-you-rather": [
    ("Would you rather be the smartest or the kindest person in the room", "i"),
    ("Would you rather live in a village or a city", "i"),
    ("Would you rather lose the internet or lose television", "i"),
    ("Would you rather always speak the truth or always be believed", "i"),
    ("Would you rather have one close friend or twenty ordinary ones", "i"),
    ("Would you rather travel to space or to the deep sea", "b"),
    ("Would you rather be famous now or respected later", "i"),
],
"my-favourite": [
    ("My favourite book and why it stayed with me", "b"),
    ("My favourite sport", "b"),
    ("My favourite place in my city", "b"),
    ("My favourite Indian food", "b"),
    ("My favourite time of the day", "i"),
    ("My favourite hobby", "b"),
    ("My favourite person from history", "p"),
    ("My favourite film and one scene from it", "b"),
    ("My favourite thing to do in the holidays", "b"),
],
"if-I-could": [
    ("If I could fix one problem in my neighbourhood", "b"),
    ("If I were the principal for a week", "b"),
    ("If I could meet any sportsperson", "b"),
    ("If I could bring back one thing from the past", "b"),
    ("If I could give every child in India one thing", "p"),
    ("If I could learn any skill instantly", "b"),
    ("If I could send a message to myself in ten years", "b"),
],
}

BANDS["12-14"] = {
"school": [
    ("What school teaches you that no exam measures", "b"),
    ("Should students grade their teachers", "b"),
    ("The pressure of board exams", "b"),
    ("Why public speaking should be taught in every school", "p"),
    ("Competition between friends", "b"),
    ("Should schools teach personal finance", "p"),
    ("The subject I would remove from the timetable", "b"),
    ("What I would tell a nervous new student", "b"),
    ("Are marks a fair measure of a student", "b"),
    ("Learning outside the classroom", "b"),
    ("Why attendance rules exist", "i"),
],
"family": [
    ("The hardest conversation I have had at home", "b"),
    ("How my parents' childhood differed from mine", "b"),
    ("Independence and trust between parents and teenagers", "b"),
    ("A family member who changed how I think", "b"),
    ("Should teenagers get a say in family decisions", "b"),
    ("What I have learned from an argument at home", "b"),
    ("Growing up in a joint family", "b"),
    ("The expectations placed on the eldest child", "b"),
],
"festivals": [
    ("Independence Day: freedom is a responsibility", "p"),
    ("Republic Day and the promise of the Constitution", "p"),
    ("Do festivals still mean what they used to", "b"),
    ("Celebrating festivals without harming the environment", "p"),
    ("Unity in diversity is not just a slogan", "p"),
    ("Gandhi Jayanti: is non-violence still practical", "p"),
    ("Teachers' Day and Dr Radhakrishnan", "p"),
    ("What festivals teach us about community", "b"),
    ("The commercialisation of festivals", "b"),
    ("A festival tradition worth protecting", "b"),
],
"animals": [
    ("Wildlife conservation in India: are we doing enough", "p"),
    ("Should animals be used for entertainment", "b"),
    ("Project Tiger and what it achieved", "p"),
    ("Vegetarianism and animal welfare", "b"),
    ("Human-animal conflict in growing cities", "p"),
    ("Why species extinction should worry us", "b"),
    ("Stray dogs: compassion versus public safety", "b"),
],
"food": [
    ("Food waste in a country that still goes hungry", "p"),
    ("Is fast food a real health crisis", "b"),
    ("Regional cuisine and cultural identity", "p"),
    ("Should junk food advertising to children be banned", "b"),
    ("The economics of the school canteen", "i"),
    ("Farmers and the food on our plate", "p"),
],
"imagination": [
    ("A day in the life of a person in 2075", "b"),
    ("If artificial intelligence had to write my exam", "b"),
    ("The invention the world still needs", "p"),
    ("If I could redesign the school system", "p"),
    ("A world where lying was impossible", "b"),
    ("If India had one extra state, what would it be for", "i"),
    ("Writing a letter to the person I will be at twenty-five", "b"),
],
"opinions": [
    ("Social media does more harm than good", "b"),
    ("Should there be an age limit for smartphones", "b"),
    ("Is failure necessary for success", "b"),
    ("Should voting be compulsory", "p"),
    ("Talent versus hard work", "b"),
    ("Does technology make us lonelier", "b"),
    ("Climate change is not a future problem", "p"),
    ("Should online classes replace some school days", "b"),
    ("Is honesty always the right policy", "b"),
    ("Reading books versus watching adaptations", "b"),
    ("Should children be allowed to choose their subjects earlier", "b"),
    ("Does money buy happiness", "b"),
    ("Gender equality begins at home", "p"),
    ("Is cricket given too much importance in India", "b"),
],
"would-you-rather": [
    ("Would you rather be misunderstood or ignored", "i"),
    ("Would you rather have security or freedom", "i"),
    ("Would you rather change one law or one habit of the whole country", "i"),
    ("Would you rather know the truth and be unhappy or not know and be content", "i"),
    ("Would you rather lead a team or work alone", "i"),
    ("Would you rather be judged by your effort or your results", "i"),
],
"my-favourite": [
    ("My favourite book and the idea it left me with", "b"),
    ("My favourite leader from Indian history", "p"),
    ("My favourite scientist and their contribution", "p"),
    ("My favourite piece of music and why it works", "b"),
    ("My favourite place I have travelled to", "b"),
    ("My favourite quote and what it demands of me", "b"),
    ("My favourite sportsperson and what they got right", "b"),
],
"if-I-could": [
    ("If I could address the nation for two minutes", "p"),
    ("If I could solve one problem in my city", "p"),
    ("If I could sit down with Dr APJ Abdul Kalam", "p"),
    ("If I could change one thing about how my generation is seen", "b"),
    ("If I could make one subject compulsory for everyone", "b"),
    ("If I could undo one invention", "b"),
    ("If I had one year with no school and no rules", "b"),
    ("If I could guarantee every Indian child one right", "p"),
],
}


# --- supplementary sets, added to reach a deep enough pool per band+mode ----
EXTRA: dict[str, dict[str, list[tuple[str, str]]]] = {
"6-8": {
    "school": [("What I like about my classroom", "i"), ("Reading time at school", "b"),
               ("My pencil box", "i"), ("A rule at school I think is fair", "i")],
    "animals": [("Butterflies", "b"), ("Why I like or fear dogs", "i"), ("The parrot", "b")],
    "food": [("Curd rice, roti or dosa: what I eat most", "i"), ("A snack I can make myself", "b")],
    "family": [("A day when my family laughed a lot", "i"), ("My cousin", "b")],
    "imagination": [("If my school bag could carry me", "i"), ("A friendly monster", "b")],
    "opinions": [("Why we should not be scared of the dark", "i"),
                 ("Why we should help our friends", "b")],
    "my-favourite": [("My favourite fruit", "i"), ("My favourite festival food", "i")],
    "would-you-rather": [("Would you rather draw or sing", "i"),
                         ("Would you rather have wings or a tail", "i")],
    "if-I-could": [("If I could be an animal for a day", "b")],
    "festivals": [("The festival lights in my street", "i")],
},
"9-11": {
    "school": [("A mistake at school that taught me something", "b"),
               ("Why break time matters", "i"), ("Learning to work with someone I disagree with", "b")],
    "opinions": [("Why reading is not boring", "b"), ("Pocket money should be earned", "b"),
                 ("Should children help with housework", "i"), ("Why plastic bags should go", "b")],
    "family": [("Something I do better than my parents", "i"),
               ("A promise I kept at home", "b")],
    "animals": [("A wild animal I have seen up close", "i"),
                ("Why forests matter to animals and to us", "p")],
    "food": [("Why my grandmother's cooking is different", "b"),
             ("A food from another state I want to try", "i")],
    "imagination": [("If my city had no traffic", "b"), ("A machine that fixes one problem", "b")],
    "festivals": [("A festival I would like to celebrate in another country", "i"),
                  ("Why I look forward to the festival holidays", "i")],
    "my-favourite": [("My favourite memory from last year", "b"),
                     ("My favourite thing to do alone", "i")],
    "if-I-could": [("If I could invite three people to dinner", "b")],
    "would-you-rather": [("Would you rather read minds or predict the weather", "i")],
},
"12-14": {
    "opinions": [("Should homework be optional", "b"), ("Is being busy the same as being productive", "b"),
                 ("Do we praise talent too much and effort too little", "b"),
                 ("Should schools ban mobile phones entirely", "b"),
                 ("Is peer pressure always negative", "b")],
    "school": [("What I would say at my own farewell", "p"),
               ("Why students should run more of the school", "b"),
               ("The teacher who changed my mind about something", "b")],
    "family": [("Privacy at home: where is the line", "b"),
               ("What I want my family to understand about me", "b"),
               ("The value of an argument you lose", "i")],
    "imagination": [("If I ran a company at fourteen", "b"),
                    ("A day when the internet stopped working everywhere", "b")],
    "festivals": [("A national day that deserves more attention", "p"),
                  ("Should festivals get public holidays", "i")],
    "food": [("Is home food always healthier", "i")],
    "animals": [("Should India ban animal testing", "p")],
    "my-favourite": [("My favourite thing I have made or built", "b"),
                     ("My favourite failure", "b")],
    "if-I-could": [("If I could speak to my whole school for one minute", "p"),
                   ("If I could remove one word from the language", "i")],
    "would-you-rather": [("Would you rather be remembered or be useful", "i"),
                         ("Would you rather have more time or more choices", "i")],
},
}

for _band, _cats in EXTRA.items():
    for _cat, _entries in _cats.items():
        BANDS[_band].setdefault(_cat, []).extend(_entries)

MODE_MAP = {
    "b": ["prepared", "impromptu"],
    "p": ["prepared"],
    "i": ["impromptu"],
}


def build() -> list[dict]:
    topics: list[dict] = []
    next_id = 1
    for band, categories in BANDS.items():
        for category, entries in categories.items():
            for text, code in entries:
                topics.append({
                    "id": next_id,
                    "text": text,
                    "age_band": band,
                    "category": category,
                    "modes": MODE_MAP[code],
                })
                next_id += 1
    return topics


if __name__ == "__main__":
    topics = build()
    seen = set()
    for t in topics:
        key = t["text"].lower()
        assert key not in seen, f"duplicate topic: {t['text']}"
        seen.add(key)
    OUT.write_text(json.dumps(topics, indent=1, ensure_ascii=False) + "\n")
    per_band: dict[str, int] = {}
    for t in topics:
        per_band[t["age_band"]] = per_band.get(t["age_band"], 0) + 1
    print(f"wrote {len(topics)} topics -> {OUT}")
    print("per band:", per_band)
