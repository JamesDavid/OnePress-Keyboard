import Foundation

// MARK: - Key mapping

enum Keys {
    static let letterKey: [Character: Character] = {
        var m: [Character: Character] = [:]
        let groups: [(Character, String)] = [("2", "abc"), ("3", "def"), ("4", "ghi"), ("5", "jkl"),
                                             ("6", "mno"), ("7", "pqrs"), ("8", "tuv"), ("9", "wxyz")]
        for (k, letters) in groups { for c in letters { m[c] = k } }
        m["'"] = "#"
        return m
    }()
    static let keyLetters: [Character: String] = ["2": "abc", "3": "def", "4": "ghi", "5": "jkl", "6": "mno",
                                                  "7": "pqrs", "8": "tuv", "9": "wxyz", "#": "'"]

    /// Keypad digits that type a word ("don't" -> "366#8").
    static func wordKeys(_ w: String) -> String {
        var s = ""
        for c in w { if let k = letterKey[c] { s.append(k) } }
        return s
    }

    // The key string holds predictive presses ('2'-'9', '0' space, '#') and, from exact
    // (multi-tap) mode, literal characters: 'a'-'z', "'", '.', ',', '?', '!',
    // and 'A'-'J' for the digits 0-9.
    static let litPunct: Set<Character> = [".", ",", "?", "!"]

    static func isWordChar(_ c: Character) -> Bool {
        return (c >= "2" && c <= "9") || (c >= "a" && c <= "z") || c == "'" || (c >= "A" && c <= "J")
    }
    /// The keypad key a stored character stands for.
    static func keyOf(_ c: Character) -> Character {
        if c >= "a" && c <= "z" { return letterKey[c] ?? c }
        if c == "'" { return "#" }
        return c
    }
    /// The exact character, or nil for a predictive press.
    static func litOf(_ c: Character) -> Character? {
        if (c >= "a" && c <= "z") || c == "'" { return c }
        if c >= "A" && c <= "J", let a = c.asciiValue { return Character(String(Int(a) - 65)) }
        return nil
    }
}

// MARK: - Model

final class WordModel {
    let words: [String]
    let display: [String?]
    let n: Int
    let punct: [String]
    let bos: Int32
    let uni: [Double]
    let rowStart: [UInt32]
    let nextIds: [UInt32]
    let counts: [UInt32]
    let ctx: [Double]
    let fullKeys: [String]
    let byKey: [String: [Int32]]
    let keyed: [(key: String, id: Int32)]
    let wordIndex: [String: Int32]
    let uniFirst: [Double]

    static let questionStarters: Set<String> = [
        "what", "where", "when", "why", "who", "whom", "whose", "which", "how",
        "can", "could", "would", "should", "will", "shall", "do", "does", "did", "is", "are", "was", "were", "am",
        "isn't", "aren't", "don't", "doesn't", "didn't", "can't", "won't", "wouldn't", "shouldn't", "couldn't",
        "have", "has", "may", "might", "want", "wanna", "need", "got", "any", "anyone", "anybody", "anything",
        "ready", "free", "you", "u"]

    private struct Reader {
        let b: [UInt8]
        var p = 0
        mutating func u32() -> UInt32 {
            let v = UInt32(b[p]) | UInt32(b[p + 1]) << 8 | UInt32(b[p + 2]) << 16 | UInt32(b[p + 3]) << 24
            p += 4
            return v
        }
        mutating func f32() -> Float { Float(bitPattern: u32()) }
        mutating func bytes(_ count: Int) -> [UInt8] {
            let s = Array(b[p..<(p + count)])
            p += count
            return s
        }
    }

    init?(url: URL) {
        guard let data = try? Data(contentsOf: url) else { return nil }
        var r = Reader(b: [UInt8](data))
        guard r.bytes(4) == Array("KPD1".utf8) else { return nil }
        let nW = Int(r.u32()), nPunct = Int(r.u32())
        let bosL = Int32(r.u32())
        let wordBytes = r.bytes(Int(r.u32()))
        let ws = String(decoding: wordBytes, as: UTF8.self)
            .split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        guard ws.count == nW else { return nil }
        var disp = [String?](repeating: nil, count: nW)
        let nDisp = Int(r.u32())
        for _ in 0..<nDisp {
            let i = Int(r.u32())
            let s = String(decoding: r.bytes(Int(r.u32())), as: UTF8.self)
            if i < nW { disp[i] = s }
        }
        var u = [Double](repeating: 0, count: Int(bosL) + 1)
        for i in 0..<nW { u[i] = exp(Double(r.f32())) }
        for i in 0..<nPunct { u[nW + i] = exp(Double(r.f32())) }
        let punctL = r.bytes(nPunct).map { String(UnicodeScalar($0)) }
        let rows = Int(r.u32())
        var rs = [UInt32](); rs.reserveCapacity(rows + 1)
        for _ in 0...rows { rs.append(r.u32()) }
        let entries = Int(r.u32())
        var nx = [UInt32](); nx.reserveCapacity(entries)
        for _ in 0..<entries { nx.append(r.u32()) }
        var cn = [UInt32](); cn.reserveCapacity(entries)
        for _ in 0..<entries { cn.append(r.u32()) }
        var c = [Double](repeating: 0, count: rows)
        for row in 0..<rows {
            var sum: UInt64 = 0
            for e in Int(rs[row])..<Int(rs[row + 1]) { sum += UInt64(cn[e]) }
            c[row] = Double(sum)
        }

        var fk = [String](); fk.reserveCapacity(nW)
        var bk: [String: [Int32]] = [:]
        var kd: [(key: String, id: Int32)] = []
        var wi: [String: Int32] = [:]
        var first = [Double](repeating: 0, count: 26)
        for (i, w) in ws.enumerated() {
            let full = Keys.wordKeys(w)
            fk.append(full)
            // Apostrophes are optional: "don't" matches both 366#8 and 3668.
            var variants = [full]
            if full.contains("#") { variants.append(full.replacingOccurrences(of: "#", with: "")) }
            for k in variants {
                bk[k, default: []].append(Int32(i))   // vocab is frequency-ordered, so lists are too
                kd.append((key: k, id: Int32(i)))
            }
            if wi[w] == nil { wi[w] = Int32(i) }
            if let a = w.unicodeScalars.first?.value, a >= 97, a < 123 { first[Int(a - 97)] += u[i] }
        }
        kd.sort { $0.key != $1.key ? $0.key < $1.key : $0.id < $1.id }

        words = ws; display = disp; n = nW; punct = punctL; bos = bosL; uni = u
        rowStart = rs; nextIds = nx; counts = cn; ctx = c
        fullKeys = fk; byKey = bk; keyed = kd; wordIndex = wi; uniFirst = first
    }

    func punctId(_ p: String) -> Int32 {
        if let i = punct.firstIndex(of: p) { return Int32(n + i) }
        return -1
    }
    func isSentenceEnd(_ id: Int32) -> Bool { id >= Int32(n) && id < bos && punct[Int(id) - n] != "," }

    func bigramCount(_ prev: Int32, _ cur: Int32) -> Double {
        var lo = Int(rowStart[Int(prev)]), hi = Int(rowStart[Int(prev) + 1])
        let target = UInt32(cur)
        while lo < hi {
            let mid = (lo + hi) / 2
            if nextIds[mid] < target { lo = mid + 1 } else { hi = mid }
        }
        if lo < Int(rowStart[Int(prev) + 1]) && nextIds[lo] == target { return Double(counts[lo]) }
        return 0
    }

    /// log P(cur | prev), interpolated (Witten-Bell style weight)
    func lp(_ prev: Int32, _ cur: Int32) -> Double {
        let pu = (cur >= 0 && Int(cur) < uni.count && uni[Int(cur)] > 0) ? uni[Int(cur)] : 1e-9
        guard prev >= 0, Int(prev) < ctx.count else { return log(pu) }
        let c = ctx[Int(prev)]
        if c == 0 { return log(pu) }
        let cb = bigramCount(prev, cur)
        let lam = c / (c + 40)
        return log(lam * cb / c + (1 - lam) * pu)
    }

    /// First index in `keyed` whose key is >= prefix.
    func lowerBound(_ prefix: String) -> Int {
        var lo = 0, hi = keyed.count
        while lo < hi {
            let mid = (lo + hi) / 2
            if keyed[mid].key < prefix { lo = mid + 1 } else { hi = mid }
        }
        return lo
    }

    func prefixCandidates(_ prefix: String, limit: Int, pred: ((Int32, String) -> Bool)?) -> [Int32] {
        var best: [Int32] = []
        var i = lowerBound(prefix)
        while i < keyed.count && keyed[i].key.hasPrefix(prefix) {
            let (key, id) = keyed[i]
            i += 1
            if let pred = pred, !pred(id, key) { continue }
            if best.contains(id) { continue }
            if best.count < limit { best.append(id); best.sort() }
            else if id < best[limit - 1] { best[limit - 1] = id; best.sort() }
        }
        return best
    }
}

// MARK: - Decoding

enum TokType { case word, punct, space }

struct Tok {
    var type: TokType
    var keys: String = ""
    var lit: [Character?] = []
    var plit: String? = nil      // exact punctuation
}

struct Cand {
    var text: String
    var id: Int32
    var partial: String? = nil
    var penalty: Double = 0
    var unknown = false
    var literal = false
}

struct Slot {
    var tok: Tok
    var tokIndex: Int
    var all: [Cand] = []
    var cands: [Cand] = []
}

struct Hyp {
    var score: Double
    var prev: Int32
    var first: Int32?
    var cf: Int32?
    var path: [Int]
}

struct Lock: Equatable { var keys: String; var text: String }

struct DecodeResult {
    var toks: [Tok]
    var slots: [Slot]
    var hyps: [Hyp]
}

struct Piece {
    var text: String
    var slot: Int          // -1 for spaces
    var partial: String?
    var unknown: Bool
}

enum WordCase { case cap, upper }

/// Where the composition sits in the host text.
struct StartContext {
    var prev: Int32          // previous word id, or bos at a sentence start
    var capFirst: Bool
}

final class Decoder {
    let m: WordModel
    init(model: WordModel) { m = model }

    func tokenize(_ keys: [Character]) -> [Tok] {
        var toks: [Tok] = []
        for i in 0..<keys.count {
            let ch = keys[i]
            let lastIsWord = toks.last?.type == .word
            if ch == "0" {
                toks.append(Tok(type: .space))
            } else if ch == "#" {
                let next: Character? = i + 1 < keys.count ? keys[i + 1] : nil
                if lastIsWord, let nx = next, Keys.isWordChar(nx) {
                    toks[toks.count - 1].keys.append("#")
                    toks[toks.count - 1].lit.append(nil)
                } else {
                    toks.append(Tok(type: .punct))
                }
            } else if Keys.litPunct.contains(ch) {
                toks.append(Tok(type: .punct, plit: String(ch)))
            } else if Keys.isWordChar(ch) {
                if lastIsWord {
                    toks[toks.count - 1].keys.append(Keys.keyOf(ch))
                    toks[toks.count - 1].lit.append(Keys.litOf(ch))
                } else {
                    toks.append(Tok(type: .word, keys: String(Keys.keyOf(ch)), lit: [Keys.litOf(ch)]))
                }
            }
        }
        return toks
    }

    /// Does word `id` (matched through key string `key`) agree with the exact letters?
    func litMatch(_ tok: Tok, _ id: Int32, _ key: String) -> Bool {
        let w = m.words[Int(id)]
        let text = Array(key.contains("#") ? w : w.replacingOccurrences(of: "'", with: ""))
        for (i, l) in tok.lit.enumerated() {
            guard let l = l else { continue }
            if i >= text.count || text[i] != l { return false }
        }
        return true
    }

    func slotCandidates(_ tok: Tok, isLast: Bool) -> [Cand] {
        if tok.type == .punct {
            if let p = tok.plit { return [Cand(text: p, id: m.punctId(p))] }
            return m.punct.enumerated().map { Cand(text: $0.element, id: Int32(m.n + $0.offset)) }
        }
        let hasLit = tok.lit.contains { $0 != nil }
        let allLit = !tok.lit.contains { $0 == nil }
        var ids = m.byKey[tok.keys] ?? []
        if hasLit { ids = ids.filter { litMatch(tok, $0, tok.keys) } }
        // A contraction typed without its apostrophe ("im" for I'm) is allowed but slightly penalized.
        var exact = ids.prefix(40).map { id in
            Cand(text: m.words[Int(id)], id: id, penalty: m.fullKeys[Int(id)] == tok.keys ? 0 : log(0.5))
        }
        if isLast && !allLit {
            // While still typing, also offer completions (shown truncated to what's typed).
            let seen = Set(exact.map { $0.id })
            let pred: ((Int32, String) -> Bool)? = hasLit ? { [self] id, key in self.litMatch(tok, id, key) } : nil
            for id in m.prefixCandidates(tok.keys, limit: 12, pred: pred) where !seen.contains(id) {
                let w = m.words[Int(id)]
                exact.append(Cand(text: String(w.prefix(tok.keys.count)), id: id, partial: w, penalty: log(0.5)))
            }
        }
        if allLit {
            // Spelled out exactly: always offer it as typed, even if it isn't in the word list.
            let typed = String(tok.lit.compactMap { $0 })
            let bare = typed.replacingOccurrences(of: "'", with: "")
            let known = exact.filter { $0.partial == nil && $0.text.replacingOccurrences(of: "'", with: "") == bare && $0.text.count == typed.count }
            if !known.isEmpty { return known }
            return [Cand(text: typed, id: -1, literal: true)]
        }
        if exact.isEmpty {
            var raw = ""
            for (i, k) in tok.keys.enumerated() {
                if let l = tok.lit[i] { raw.append(l) } else { raw.append(Keys.keyLetters[k]?.first ?? "?") }
            }
            exact.append(Cand(text: raw, id: -1, unknown: true))
        }
        return exact
    }

    func decode(_ keys: [Character], locks: [Int: Lock], start: StartContext, beamWidth: Int = 40, nBest: Int = 1) -> DecodeResult {
        let toks = tokenize(keys)
        var slots: [Slot] = []
        for (i, t) in toks.enumerated() where t.type != .space { slots.append(Slot(tok: t, tokIndex: i)) }
        let lastTokIsWord = toks.last?.type == .word
        for j in 0..<slots.count {
            let isLast = j == slots.count - 1 && lastTokIsWord
            var c = slotCandidates(slots[j].tok, isLast: isLast)
            slots[j].all = c
            if let lock = locks[j], lock.keys == slots[j].tok.keys {
                let hit = c.filter { ($0.partial ?? $0.text) == lock.text }
                if !hit.isEmpty { c = hit }
            }
            slots[j].cands = c
        }

        var beam = [Hyp(score: 0, prev: start.prev, first: nil, cf: nil, path: [])]
        for (j, s) in slots.enumerated() {
            let isFinal = j == slots.count - 1
            var next: [Hyp] = []
            next.reserveCapacity(beam.count * s.cands.count)
            for h in beam {
                for (ci, c) in s.cands.enumerated() {
                    var step = c.id < 0 ? (c.literal ? -14 : -25) : m.lp(h.prev, c.id) + c.penalty
                    var prev: Int32 = c.id < 0 ? -1 : c.id
                    var first = h.first, cf = h.cf
                    if c.id >= Int32(m.n) {
                        // Punctuation: a word-pair model can't see how the sentence began,
                        // so use the sentence's first word to judge question vs statement.
                        let q = [first, cf].contains { f in
                            guard let f = f, f >= 0, Int(f) < m.n else { return false }
                            return WordModel.questionStarters.contains(m.words[Int(f)])
                        }
                        if c.text == "?" { step += q ? 2.5 : -1.5 }
                        else if c.text == "." && q { step -= 1.5 }
                        else if c.text == "," && isFinal { step -= 3 }
                        if c.text != "," { prev = m.bos; first = nil }
                        cf = nil
                    } else {
                        if first == nil { first = c.id }
                        if cf == nil { cf = c.id }
                    }
                    next.append(Hyp(score: h.score + step, prev: prev, first: first, cf: cf, path: h.path + [ci]))
                }
            }
            next.sort { $0.score > $1.score }
            beam = Array(next.prefix(beamWidth))
        }
        return DecodeResult(toks: toks, slots: slots, hyps: Array(beam.prefix(nBest)))
    }

    /// Display text with sentence capitalization and per-word shift/caps.
    func render(_ r: DecodeResult, _ hyp: Hyp, start: StartContext, cases: [Int: WordCase]) -> [Piece] {
        var bySlotTok: [Int: Int] = [:]
        for (j, s) in r.slots.enumerated() { bySlotTok[s.tokIndex] = j }
        var capNext = start.capFirst
        var wordOrdinal = 0
        var pieces: [Piece] = []
        for (i, t) in r.toks.enumerated() {
            if t.type == .space { pieces.append(Piece(text: " ", slot: -1, partial: nil, unknown: false)); continue }
            guard let j = bySlotTok[i] else { continue }
            let c = r.slots[j].cands[hyp.path[j]]
            var text = c.text
            var partial: String? = nil
            if t.type == .word {
                if c.id >= 0, Int(c.id) < m.n, let shown = m.display[Int(c.id)] {
                    text = c.partial != nil ? String(shown.prefix(text.count)) : shown
                }
                if text == "i" || text.hasPrefix("i'") { text = "I" + String(text.dropFirst()) }
                // keep brand styling like iPhone / eBay at the start of a sentence
                let keepStyle = text.count > 1 && text.first!.isLowercase && Array(text)[1].isUppercase
                if capNext && !keepStyle { text = text.prefix(1).uppercased() + String(text.dropFirst()) }
                capNext = false
                if let p = c.partial { partial = (c.id >= 0 && Int(c.id) < m.n ? m.display[Int(c.id)] : nil) ?? p }
                switch cases[wordOrdinal] {
                case .cap?: text = text.prefix(1).uppercased() + String(text.dropFirst())
                case .upper?: text = text.uppercased()
                case nil: break
                }
                wordOrdinal += 1
            } else {
                capNext = text != ","
            }
            pieces.append(Piece(text: text, slot: j, partial: partial, unknown: c.unknown))
        }
        return pieces
    }

    // MARK: Next-letter probabilities (for sizing QWERTY keys)

    func nextLetterProbs(_ r: DecodeResult?, _ hyp: Hyp?, start: StartContext) -> [Double]? {
        var p = [Double](repeating: 0, count: 26)
        func prevContext(_ slotIndex: Int) -> Int32 {
            guard let r = r, let hyp = hyp, slotIndex >= 0 else { return start.prev }
            let c = r.slots[slotIndex].cands[hyp.path[slotIndex]]
            if c.id < 0 { return -1 }
            if c.id >= Int32(m.n) && c.text != "," { return m.bos }
            return c.id
        }
        if let r = r, let last = r.toks.last, last.type == .word {
            // Word in progress: weight every word that starts with these keys by P(word | previous word).
            let k = last.keys, prev = prevContext(r.slots.count - 2)
            var seen = Set<Int32>()
            var i = m.lowerBound(k)
            let kLen = k.count
            while i < m.keyed.count && m.keyed[i].key.hasPrefix(k) {
                let (key, id) = m.keyed[i]
                i += 1
                if key.count <= kLen || seen.contains(id) { continue }
                seen.insert(id)
                let w = m.words[Int(id)]
                let text = key.contains("#") ? w : w.replacingOccurrences(of: "'", with: "")
                let chars = Array(text.unicodeScalars)
                if kLen < chars.count {
                    let v = Int(chars[kLen].value) - 97
                    if v >= 0 && v < 26 { p[v] += exp(m.lp(prev, id)) }
                }
            }
        } else {
            // Start of a word: mix the bigram row for the previous word with first-letter frequencies.
            let prev = prevContext((r?.slots.count ?? 0) - 1)
            let baseSum = m.uniFirst.reduce(0, +)
            var lam = 0.0, ctxN = 0.0
            if prev >= 0, Int(prev) < m.ctx.count { ctxN = m.ctx[Int(prev)]; lam = ctxN > 0 ? ctxN / (ctxN + 40) : 0 }
            for c in 0..<26 { p[c] = (1 - lam) * m.uniFirst[c] / baseSum }
            if lam > 0 {
                for e in Int(m.rowStart[Int(prev)])..<Int(m.rowStart[Int(prev) + 1]) {
                    let id = Int(m.nextIds[e])
                    guard id < m.n, let a = m.words[id].unicodeScalars.first?.value else { continue }
                    let v = Int(a) - 97
                    if v >= 0 && v < 26 { p[v] += lam * Double(m.counts[e]) / ctxN }
                }
            }
        }
        let sum = p.reduce(0, +)
        guard sum > 0 else { return nil }
        return p.map { $0 / sum }
    }
}
