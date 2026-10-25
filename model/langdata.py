"""Words that attach to the word before them with a hyphen, per language: French inversion
(est-ce, a-t-il, dis-moi) and Portuguese clitics (dá-me, chama-se). They are words of their own
in a model, written with the hyphen ("-ce"); prep_tatoeba.py keeps a hyphen only before one of
them (any other hyphen becomes a space), build_model.py splits the text before them, and the
decoders split a word typed with # before one ("est#ce": est + -ce, shown joined).
"""
HYPHENS = {
    "fr": ["ce", "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "moi", "toi", "lui", "leur",
           "les", "le", "la", "y", "en", "là", "ci", "même", "mêmes", "t"],
    "pt": ["me", "te", "se", "lhe", "lhes", "nos", "vos", "o", "a", "os", "as", "lo", "la", "los", "las",
           "no", "na", "nas"],
}
