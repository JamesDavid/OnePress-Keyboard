# Data and licenses

The code in this repository is under the [PolyForm Noncommercial License 1.0.0](LICENSE):
noncommercial use only; commercial use needs a separate license from the author.

The model files (`model/onepress.bin`, `model/onepress-m.bin`, `model/onepress-s.bin`, the Spanish,
German, Portuguese and French `model/onepress-es*.bin`, `onepress-de.bin`, `onepress-pt.bin`, `onepress-fr.bin`, and the neural models `model/onepress-nn.bin`, `model/onepress-nn-s.bin` and `model/onepress-nn-m.bin`) contain statistics derived from the datasets below: word
frequencies, word-pair and word-triple probabilities, casing, and neural network weights. They
contain no text from the datasets. Because the word frequencies come from wordfreq, whose data
is licensed CC BY-SA 4.0, **the model files are licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)**. You may use them in any app,
including a commercial one, as long as you credit the sources below and share changes to the
model files themselves under the same license. Your own code that loads them is not affected
(the decoders that read them are covered by the code license above).

The corpora are not stored here; `model/fetch_corpora.sh` downloads them.

| Source | Used for | Terms |
|---|---|---|
| [wordfreq](https://github.com/rspeer/wordfreq) by Robyn Speer | vocabulary, word frequencies, and which words start or end compounds (snow-man) | Data [CC BY-SA 4.0](https://github.com/rspeer/wordfreq/blob/master/NOTICE.md) (code Apache 2.0) |
| [NUS SMS Corpus](https://github.com/kite1988/nus-sms-corpus), Tao Chen and Min-Yen Kan | word pairs, neural model, and the held-out evaluation | Public domain ("released to the general domain, copyright-free"); please cite the paper below |
| [Topical-Chat](https://github.com/alexa/Topical-Chat) (Amazon) | word pairs and triples, casing, neural model (train split); its test and validation splits are a second held-out evaluation, never trained on | [CDLA-Sharing-1.0](https://github.com/alexa/Topical-Chat/blob/master/DATALICENSE); places no restrictions on results such as trained models |
| [Taskmaster-1](https://github.com/google-research-datasets/Taskmaster) (Google) | word pairs and triples, casing, neural model | CC BY 4.0 |
| [Synthetic-Persona-Chat](https://huggingface.co/datasets/google/Synthetic-Persona-Chat) (Google) | word pairs and triples, casing, neural model | CC BY 4.0 |
| Project Gutenberg selections (via NLTK) | word pairs and triples, casing, neural model | Public domain |
| Movie Review Data, Bo Pang and Lillian Lee (via NLTK) | word pairs and triples, neural model | CC BY 4.0 |
| Names Corpus v1.3, Mark Kantrowitz, additions by Bill Ross (via NLTK) | first names in the vocabulary | Free to use with credit; names from it are in the model's vocabulary, so its README is included as [`model/data/NAMES-README.txt`](model/data/NAMES-README.txt) |
| [Tatoeba](https://tatoeba.org) Spanish, German, Portuguese and French sentences | those languages' models: word pairs and triples, casing (train split); their test splits are the evaluation | [CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/) |
| `model/data/messages.txt`, `model/data/proper.txt` | everyday messages, brand and place names | Written for this project; same license as the code |

Earlier versions also used the NLTK Brown corpus and webtext. They were removed: NLTK lists
Brown as non-commercial, and webtext has no stated license.

## Attribution

Include this, or equivalent, wherever you ship the model files:

> Word model from OnePress (github.com/JamesDavid/OnePress-Keyboard), CC BY-SA 4.0. Built with
> word frequencies from wordfreq by Robyn Speer (CC BY-SA 4.0), which draws on SUBTLEX,
> OpenSubtitles, Google Books Ngram Viewer, the Leeds Internet Corpus, Wikipedia and
> ParaCrawl; the NUS SMS Corpus (Tao Chen and Min-Yen Kan); Topical-Chat (Amazon,
> CDLA-Sharing-1.0); Taskmaster-1 and Synthetic-Persona-Chat (Google, CC BY 4.0); Movie Review
> Data (Bo Pang and Lillian Lee, CC BY 4.0); the Names Corpus (© 1991 Mark Kantrowitz,
> additions by Bill Ross); and Project Gutenberg texts. The Spanish, German, Portuguese and French
> models (onepress-es*.bin, onepress-de.bin, onepress-pt.bin, onepress-fr.bin) also use sentences from Tatoeba
> (tatoeba.org, CC BY 2.0 FR).

NUS SMS Corpus citation: Tao Chen and Min-Yen Kan (2013). Creating a Live, Public Short
Message Service Corpus: The NUS SMS Corpus. *Language Resources and Evaluation*, 47(2):299–355.

This summary is our reading of each source's terms, not legal advice.
