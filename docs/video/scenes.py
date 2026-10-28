# The tutorial video: each scene is a title and a list of steps.
#   ('say', text)            start a narration line once the one before has finished
#   ('say', text, spoken)    the same, spoken differently from the caption
#   ('wait',)                wait for the narration to finish
#   ('keys', '46 0 4663')    press keys; H4 holds 4; spaces only separate groups
#   ('pause', s), ('clear',), ('chip', 'home'), ('send',)
SCENES = [
    ('OnePress', [
        ('pause', 0.8),
        ('say', 'This is OnePress, a single-press keypad: you press each key just once per letter.'),
        ('say', 'A word model works out which letters you meant. Here is how to use it.'),
        ('wait',), ('pause', 0.4),
    ]),
    ('One press per letter', [
        ('say', "Each key has three or four letters, but you don't tap a key several times to reach one. You press it once."),
        ('say', 'To type hi, press 4, then 4 again.', 'To type hi, press four, then four again.'),
        ('pause', 1.6), ('keys', '4'), ('pause', 0.7), ('keys', '4'),
        ('wait',), ('pause', 0.3),
        ('say', '4 4 could be gh, gi or ih. It knew you meant hi. 0 is the space.',
         'Four four could be G H, G I, or I H. It knew you meant hi. Zero is the space.'),
        ('pause', 3.4), ('keys', '0'),
        ('wait',), ('pause', 0.5),
    ]),
    ('It reads the whole sentence', [
        ('clear',),
        ('say', "It reads the whole sentence. Let's type on my way home.", "It reads the whole sentence. Let's type: on my way home."),
        ('pause', 2.0), ('keys', '66 0 69 0 929 0'), ('wait',),
        ('say', 'Watch the last word as it comes in.'),
        ('pause', 1.0), ('keys', '4663'),
        ('wait',), ('pause', 0.4),
        ('say', 'Alone, those keys are usually "good". After "on my way", it picked "home".',
         'Alone, those keys are usually good. After on my way, it picked home.'),
        ('wait',), ('pause', 0.6),
    ]),
    ('Other guesses', [
        ('clear',), ('keys', '4663'),
        ('say', 'Here the same keys gave "good". The other words they could be are listed under the display.',
         'Here the same keys gave good. The other words they could be are listed under the display.'),
        ('wait',),
        ('say', 'Tap one to use it.'), ('pause', 0.9), ('chip', 'goodbye'),
        ('wait',),
        ('say', 'Picking a word locks it in, and the rest of the sentence decodes around it. You can tap any word on the display to see its guesses too.'),
        ('wait',), ('pause', 0.5),
    ]),
    ('Fix an earlier word', [
        ('clear',),
        ('say', 'Without touching the screen, you can still fix an earlier word. Type go home now.',
         'Without touching the screen, you can still fix an earlier word. Type: go home now.'),
        ('pause', 3.6), ('keys', '46 0 4663 0 669'), ('wait',),
        ('say', 'Hold * to select the word before.', 'Hold star to select the word before.'),
        ('pause', 0.8), ('keys', 'H*'), ('wait',),
        ('say', 'Press * for its next guess.', 'Press star for its next guess.'),
        ('pause', 1.0), ('keys', '*'), ('wait',), ('pause', 0.3),
        ('say', '"Home" became "good", and "go" changed to fit: "I\'m good now". 0 and # move between words.',
         'Home became good, and go changed to fit: I\'m good now. Zero and pound move between words.'),
        ('wait',),
        ('say', 'Hold * again to go back to the end. And 1 deletes.', 'Hold star again to go back to the end. And one deletes.'),
        ('pause', 0.9), ('keys', 'H*'), ('pause', 1.4), ('keys', '1'), ('pause', 0.3), ('keys', '1'), ('pause', 0.3), ('keys', '1'),
        ('wait',), ('pause', 0.5),
    ]),
    ('Punctuation', [
        ('clear',),
        ('say', '# is punctuation. Type ok, 6 5, and press #.', 'Pound is punctuation. Type okay, six five, and press pound.'),
        ('pause', 2.4), ('keys', '6'), ('pause', 0.3), ('keys', '5'), ('pause', 0.8), ('keys', '#'),
        ('wait',),
        ('say', 'It chose a period. It picks the mark from the sentence, so "how are you" gets a question mark.',
         'It chose a period. It picks the mark from the sentence, so how are you gets a question mark.'),
        ('pause', 1.4), ('clear',), ('keys', '469 0 273 0 968 #'),
        ('wait',),
        ('say', 'If the mark is wrong, press * for the next one.', 'If the mark is wrong, press star for the next one.'),
        ('wait',), ('pause', 0.3),
        ('say', "Between letters, # is an apostrophe, and you can leave it out: 3 6 6 8 gives don't.",
         "Between letters, pound is an apostrophe, and you can leave it out. Three six six eight gives don't."),
        ('pause', 1.0), ('clear',), ('pause', 3.6), ('keys', '3668'),
        ('wait',), ('pause', 0.6),
    ]),
    ('Numbers', [
        ('clear',),
        ('say', 'For a digit, hold its key. Hold 4, then type ever: 3 8 3 7.', 'For a digit, hold its key. Hold four, then type ever. Three eight three seven.'),
        ('pause', 2.0), ('keys', 'H4'), ('pause', 1.4), ('keys', '3837'),
        ('wait',),
        ('say', '# between digits makes times and money. "At", then 5 # 3 0, with the digits held, gives 5:30.',
         'Pound between digits makes times and money. At, then five pound three zero, with the digits held, gives five thirty.'),
        ('pause', 0.6), ('clear',), ('pause', 1.6), ('keys', '28 0'), ('pause', 1.2), ('keys', 'H5 # H3 H0'),
        ('wait',), ('pause', 0.6),
    ]),
    ('Exact spelling', [
        ('clear',),
        ('say', "For names the model doesn't know, hold # to spell exactly. The display gets a blue outline.",
         "For names the model doesn't know, hold pound to spell exactly. The display gets a blue outline."),
        ('pause', 2.4), ('keys', 'H#'), ('wait',),
        ('say', 'Now press a key again to cycle its letters: 5 5 is k, 2 is a, 4 4 4 is i.',
         'Now press a key again to cycle its letters. Five five is K, two is A, four four four is I.'),
        ('pause', 3.7), ('keys', '55'), ('pause', 0.7), ('keys', '2'), ('pause', 0.6), ('keys', '444'),
        ('wait',),
        ('say', 'Hold # again to go back to normal typing.', 'Hold pound again to go back to normal typing.'),
        ('pause', 0.8), ('keys', 'H#'),
        ('wait',), ('pause', 0.5),
    ]),
    ('Handles and addresses', [
        ('clear',),
        ('say', '# before a word makes a handle: # then john gives @John.',
         'Pound before a word makes a handle. Pound, then john, gives at John.'),
        ('pause', 3.0), ('keys', '#5646'),
        ('wait',),
        ('say', 'In an address, # is the dot. john # last # gmail # com is an email address.',
         'In an address, pound is the dot. John, pound, last, pound, G mail, pound, com, is an email address.'),
        ('pause', 1.0), ('clear',), ('pause', 1.0), ('keys', '5646 # 5278 # 46245 # 266'),
        ('wait',), ('pause', 0.8),
    ]),
    ('Send', [
        ('clear',), ('keys', '733 0 968 0 7666'),
        ('say', 'When the message is ready, press Send.'),
        ('pause', 1.6), ('send',), ('wait',),
        ('say', 'It copies the text, clears the display, and learns from it: your words, the words you use together, and your punctuation.'),
        ('wait',), ('pause', 0.5),
    ]),
    ("You're set", [
        ('say', 'That covers the keypad. The Tutorial button next to the title walks through these steps any time. Thanks for watching.'),
        ('wait',), ('pause', 1.5),
    ]),
]


def lines():
    out = []
    for _, steps in SCENES:
        for s in steps:
            if s[0] == 'say':
                out.append({'text': s[1], 'say': s[2] if len(s) > 2 else s[1]})
    return out
