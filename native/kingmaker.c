/*
 * Kingmaker native engine: American checkers.
 *
 * 32-square bitboards, principal-variation alpha-beta, transposition table,
 * history ordering, capture extensions. Each km_analyze call owns all of its
 * state, so several searches can run at once from different threads.
 *
 * Build:  cc -O3 -shared -fPIC native/kingmaker.c -o libkingmaker.so
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#define KM_EXPORT __declspec(dllexport)
static double now_ms(void) { return (double)GetTickCount64(); }
#else
#include <time.h>
#define KM_EXPORT __attribute__((visibility("default")))
static double now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000.0 + t.tv_nsec / 1e6;
}
#endif

#define POP(x) ((int)__builtin_popcount(x))
#define CTZ(x) ((int)__builtin_ctz(x))

#define MAXP 128
#define MS 96
#define WIN 10000
#define INF 32000
#define TT_BITS 22

/* ------------------------------------------------------------------ tables */
static int8_t COL32[32];
static int8_t SD[32][2], SU[32][2], SDN[32], SUN[32];
static int8_t JD[32][2][2], JU[32][2][2], JDN[32], JUN[32];
static uint64_t ZOB[32][4], ZSIDE;
static int g_init = 0;
static uint32_t CENTER, EDGE, MAINDIAG;

static int idx32(int r, int c) {
    if (r < 0 || r > 7 || c < 0 || c > 7 || ((r + c) & 1) == 0) return -1;
    return r * 4 + (c >> 1);
}
static uint64_t splitmix(uint64_t *s) {
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

KM_EXPORT void km_init(void) {
    if (g_init) return;
    for (int i = 0; i < 32; i++) {
        int r = i >> 2;
        COL32[i] = (r & 1) ? 2 * (i & 3) : 2 * (i & 3) + 1;
    }
    for (int i = 0; i < 32; i++) {
        int r = i >> 2, c = COL32[i];
        SDN[i] = SUN[i] = JDN[i] = JUN[i] = 0;
        for (int k = 0; k < 2; k++) {
            int dc = k ? 1 : -1, t, m, l;
            if ((t = idx32(r + 1, c + dc)) >= 0) SD[i][SDN[i]++] = (int8_t)t;
            if ((t = idx32(r - 1, c + dc)) >= 0) SU[i][SUN[i]++] = (int8_t)t;
            m = idx32(r + 1, c + dc); l = idx32(r + 2, c + 2 * dc);
            if (m >= 0 && l >= 0) { JD[i][JDN[i]][0] = (int8_t)m; JD[i][JDN[i]][1] = (int8_t)l; JDN[i]++; }
            m = idx32(r - 1, c + dc); l = idx32(r - 2, c + 2 * dc);
            if (m >= 0 && l >= 0) { JU[i][JUN[i]][0] = (int8_t)m; JU[i][JUN[i]][1] = (int8_t)l; JUN[i]++; }
        }
    }
    uint64_t seed = 0x5EED1234ULL;
    for (int i = 0; i < 32; i++) for (int t = 0; t < 4; t++) ZOB[i][t] = splitmix(&seed);
    ZSIDE = splitmix(&seed);
    {
        static const int c[] = { 10, 11, 14, 15, 18, 19, 22, 23 }, d[] = { 4, 8, 11, 15, 18, 22, 25, 29 };
        uint32_t e = 0, cm = 0, dm = 0;
        for (int i = 0; i < 32; i++) if (COL32[i] == 0 || COL32[i] == 7) e |= 1u << i;
        for (int i = 0; i < 8; i++) { cm |= 1u << (c[i] - 1); dm |= 1u << (d[i] - 1); }
        EDGE = e; CENTER = cm; MAINDIAG = dm;
    }
    g_init = 1;
}

/* ------------------------------------------------------------------ types */
typedef struct { uint32_t bm, bk, rm, rk; uint64_t h; } Pos;
typedef struct { uint32_t caps; int8_t from, to, plen; int8_t path[16]; } Move;
typedef struct { uint32_t key; int16_t score; int16_t move; int8_t depth; uint8_t flag; } TTE;

typedef struct {
    uint64_t nodes;
    double deadline;
    volatile int32_t *stop;
    int aborted;
    TTE *tt;
    int32_t hist[1024];
    Move mv[MAXP][MS];
    int32_t sc[MAXP][MS];
} Search;

typedef struct { int8_t path[16]; int8_t plen; int8_t ncaps; int8_t caps[12]; } OutMove;
typedef struct {
    int32_t score, depth, nmoves, npv;
    uint64_t nodes;
    OutMove best;
    OutMove pv[8];
} Result;
typedef void (*ProgressFn)(int32_t depth, int32_t score, uint64_t nodes, const OutMove *best);

/* ------------------------------------------------------------------ move generation */
typedef struct { Move *out; int n; uint32_t occ, opp; int wp; } Gen;

static void rec(Gen *g, int origin, int to, uint32_t caps, const int8_t *path, int plen) {
    if (g->n >= MS) return;
    Move *m = &g->out[g->n++];
    m->from = (int8_t)origin; m->to = (int8_t)to; m->caps = caps; m->plen = (int8_t)plen;
    if (g->wp) memcpy(m->path, path, (size_t)plen);
}

static void jumps(Gen *g, int origin, int sq, int king, int side, uint32_t caps, int8_t *path, int plen) {
    int found = 0;
    for (int dir = 0; dir < 2; dir++) {
        if (!(king || (dir == 0 && side > 0) || (dir == 1 && side < 0))) continue;
        int cnt = dir ? JUN[sq] : JDN[sq];
        for (int k = 0; k < cnt; k++) {
            int mid = dir ? JU[sq][k][0] : JD[sq][k][0];
            int land = dir ? JU[sq][k][1] : JD[sq][k][1];
            if (!((g->opp >> mid) & 1) || ((caps >> mid) & 1)) continue;
            if (((g->occ >> land) & 1) && land != origin) continue;
            found = 1;
            uint32_t nc = caps | (1u << mid);
            path[plen] = (int8_t)land;
            int crowned = !king && (side > 0 ? land >= 28 : land <= 3);
            if (crowned) rec(g, origin, land, nc, path, plen + 1);
            else jumps(g, origin, land, king, side, nc, path, plen + 1);
        }
    }
    if (!found && caps) rec(g, origin, sq, caps, path, plen);
}

static int gen(Move *out, const Pos *p, int side, int wp) {
    Gen g;
    g.out = out; g.n = 0; g.wp = wp;
    g.occ = p->bm | p->bk | p->rm | p->rk;
    uint32_t men = side > 0 ? p->bm : p->rm, kings = side > 0 ? p->bk : p->rk;
    g.opp = side > 0 ? (p->rm | p->rk) : (p->bm | p->bk);
    int8_t path[16];
    for (uint32_t m = men; m; m &= m - 1) { int sq = CTZ(m); path[0] = (int8_t)sq; jumps(&g, sq, sq, 0, side, 0, path, 1); }
    for (uint32_t m = kings; m; m &= m - 1) { int sq = CTZ(m); path[0] = (int8_t)sq; jumps(&g, sq, sq, 1, side, 0, path, 1); }
    if (g.n) return g.n;
    for (uint32_t m = men; m; m &= m - 1) {
        int sq = CTZ(m);
        int cnt = side > 0 ? SDN[sq] : SUN[sq];
        for (int k = 0; k < cnt; k++) {
            int t = side > 0 ? SD[sq][k] : SU[sq][k];
            if (!((g.occ >> t) & 1)) { path[0] = (int8_t)sq; path[1] = (int8_t)t; rec(&g, sq, t, 0, path, 2); }
        }
    }
    for (uint32_t m = kings; m; m &= m - 1) {
        int sq = CTZ(m);
        for (int d = 0; d < 2; d++) {
            int cnt = d ? SUN[sq] : SDN[sq];
            for (int k = 0; k < cnt; k++) {
                int t = d ? SU[sq][k] : SD[sq][k];
                if (!((g.occ >> t) & 1)) { path[0] = (int8_t)sq; path[1] = (int8_t)t; rec(&g, sq, t, 0, path, 2); }
            }
        }
    }
    return g.n;
}

static Pos make(const Pos *p, int side, const Move *m) {
    Pos q = *p;
    uint32_t fb = 1u << m->from, tb = 1u << m->to, c = m->caps;
    uint64_t h = q.h;
    int t0, t1;
    if (side > 0) {
        int king = (q.bk & fb) != 0;
        t0 = king ? 1 : 0;
        for (uint32_t x = c; x; x &= x - 1) { int s = CTZ(x); h ^= ZOB[s][(q.rk >> s) & 1 ? 3 : 2]; }
        q.bm &= ~fb; q.bk &= ~fb; q.rm &= ~c; q.rk &= ~c;
        if (king || m->to >= 28) { q.bk |= tb; t1 = 1; } else { q.bm |= tb; t1 = 0; }
    } else {
        int king = (q.rk & fb) != 0;
        t0 = king ? 3 : 2;
        for (uint32_t x = c; x; x &= x - 1) { int s = CTZ(x); h ^= ZOB[s][(q.bk >> s) & 1 ? 1 : 0]; }
        q.rm &= ~fb; q.rk &= ~fb; q.bm &= ~c; q.bk &= ~c;
        if (king || m->to <= 3) { q.rk |= tb; t1 = 3; } else { q.rm |= tb; t1 = 2; }
    }
    q.h = h ^ ZOB[m->from][t0] ^ ZOB[m->to][t1] ^ ZSIDE;
    return q;
}

static uint64_t hash_pos(const Pos *p, int side) {
    uint64_t h = 0;
    const uint32_t b[4] = { p->bm, p->bk, p->rm, p->rk };
    for (int t = 0; t < 4; t++) for (uint32_t x = b[t]; x; x &= x - 1) h ^= ZOB[CTZ(x)][t];
    if (side < 0) h ^= ZSIDE;
    return h;
}

/* ------------------------------------------------------------------ evaluation */
static const int ADV[8] = { 0, 3, 7, 12, 18, 26, 38, 0 };
static uint32_t ROWM(int r) { return 0xFu << (4 * r); }

static int evaluate(const Pos *p, int side) {
    uint32_t bm = p->bm, bk = p->bk, rm = p->rm, rk = p->rk;
    int nbm = POP(bm), nbk = POP(bk), nrm = POP(rm), nrk = POP(rk);
    int sc = 100 * (nbm - nrm) + 155 * (nbk - nrk);
    for (int r = 1; r < 7; r++) sc += ADV[r] * POP(bm & ROWM(r)) - ADV[7 - r] * POP(rm & ROWM(r));
    sc += 6 * (POP(bm & CENTER) - POP(rm & CENTER)) + 10 * (POP(bk & CENTER) - POP(rk & CENTER));
    sc -= 4 * (POP(bm & EDGE) - POP(rm & EDGE)) + 8 * (POP(bk & EDGE) - POP(rk & EDGE));
    if (nrm > 0) sc += 9 * POP(bm & 0x5u) + 3 * POP(bm & 0xAu);
    if (nbm > 0) sc -= 9 * POP(rm & 0xA0000000u) + 3 * POP(rm & 0x50000000u);
    uint32_t empty = ~(bm | bk | rm | rk);
    uint32_t bd = bm | bk, rd = rm | rk;
    int mb = POP(((bd << 4) | ((bd & 0xE0E0E0E0u) << 3) | ((bd & 0x07070707u) << 5)) & empty)
           + POP(((bk >> 4) | ((bk & 0x07070707u) >> 3) | ((bk & 0xE0E0E0E0u) >> 5)) & empty);
    int mr = POP(((rd >> 4) | ((rd & 0x07070707u) >> 3) | ((rd & 0xE0E0E0E0u) >> 5)) & empty)
           + POP(((rk << 4) | ((rk & 0xE0E0E0E0u) << 3) | ((rk & 0x07070707u) << 5)) & empty);
    sc += 2 * (mb - mr);
    int tot = nbm + nbk + nrm + nrk;
    int diff = (nbm - nrm) * 100 + (nbk - nrk) * 155;
    if (diff) {
        int lead = diff > 0 ? 1 : -1, ad = diff > 0 ? diff : -diff;
        sc += lead * (ad > 300 ? 300 : ad) * (24 - tot) / 60;
        if (tot <= 8 && ad >= 100 && (nbk + nrk) > 0) {
            uint32_t lm = lead > 0 ? (bm | bk) : (rm | rk), om = lead > 0 ? (rm | rk) : (bm | bk);
            int na = 0, nb = 0, ds = 0;
            for (uint32_t a = lm; a; a &= a - 1) {
                int sa = CTZ(a); na++;
                nb = 0;
                for (uint32_t b = om; b; b &= b - 1) {
                    int sb = CTZ(b); nb++;
                    int dr = (sa >> 2) - (sb >> 2), dc = COL32[sa] - COL32[sb];
                    if (dr < 0) dr = -dr;
                    if (dc < 0) dc = -dc;
                    ds += dr > dc ? dr : dc;
                }
            }
            if (na && nb) sc += lead * (48 * na * nb - 6 * ds) / (na * nb);
        }
        if (tot <= 7 && ad >= 100) { if (lead > 0) sc -= 10 * POP(rk & MAINDIAG); else sc += 10 * POP(bk & MAINDIAG); }
    }
    return side > 0 ? sc : -sc;
}

/* ------------------------------------------------------------------ search */
static int search(Search *S, int ply, const Pos *pos, int side, int depth, int alpha, int beta) {
    if ((++S->nodes & 4095) == 0 && (now_ms() > S->deadline || (S->stop && *S->stop))) S->aborted = 1;
    if (S->aborted) return 0;
    Move *mv = S->mv[ply];
    int32_t *sc = S->sc[ply];
    int n = gen(mv, pos, side, 0);
    if (n == 0) return -(WIN - ply);
    int capture = mv[0].caps != 0;
    if ((depth <= 0 && !capture) || ply >= MAXP - 3) return evaluate(pos, side);

    uint64_t h = pos->h;
    TTE *e = &S->tt[h & ((1u << TT_BITS) - 1)];
    uint32_t key = (uint32_t)(h >> 32);
    int ttm = -1;
    if (depth > 0 && e->depth > 0 && e->key == key) {
        ttm = e->move;
        if (e->depth >= depth) {
            int s = e->score;
            if (s > WIN - 200) s -= ply; else if (s < -WIN + 200) s += ply;
            if (e->flag == 0 || (e->flag == 1 && s >= beta) || (e->flag == 2 && s <= alpha)) return s;
        }
    }
    for (int i = 0; i < n; i++) {
        int code = mv[i].from * 32 + mv[i].to;
        sc[i] = code == ttm ? 1000000000 : (mv[i].caps ? 1000000 : S->hist[code]);
    }
    int alpha0 = alpha, best = -INF, bestcode = -1;
    for (int i = 0; i < n; i++) {
        int bi = i;
        for (int j = i + 1; j < n; j++) if (sc[j] > sc[bi]) bi = j;
        if (bi != i) { Move t = mv[i]; mv[i] = mv[bi]; mv[bi] = t; int32_t ts = sc[i]; sc[i] = sc[bi]; sc[bi] = ts; }
        Move m = mv[i];
        Pos child = make(pos, side, &m);
        int nd = (n == 1 && m.caps) ? depth : depth - 1, v;
        if (i == 0) v = -search(S, ply + 1, &child, -side, nd, -beta, -alpha);
        else {
            v = -search(S, ply + 1, &child, -side, nd, -alpha - 1, -alpha);
            if (v > alpha && v < beta && !S->aborted) v = -search(S, ply + 1, &child, -side, nd, -beta, -alpha);
        }
        if (S->aborted) return 0;
        if (v > best) { best = v; bestcode = m.from * 32 + m.to; if (v > alpha) alpha = v; }
        if (alpha >= beta) { if (!m.caps) S->hist[m.from * 32 + m.to] += depth * depth; break; }
    }
    if (depth > 0) {
        int flag = best <= alpha0 ? 2 : (best >= beta ? 1 : 0);
        int s = best;
        if (s > WIN - 200) s += ply; else if (s < -WIN + 200) s -= ply;
        if (e->depth == 0 || e->depth <= depth || e->key != key) {
            e->key = key; e->depth = (int8_t)(depth > 100 ? 100 : depth); e->score = (int16_t)s;
            e->flag = (uint8_t)flag; e->move = (int16_t)(flag == 2 ? -1 : bestcode);
        }
    }
    return best;
}

static void to_out(const Move *m, OutMove *o) {
    memset(o, 0, sizeof *o);
    o->plen = m->plen;
    memcpy(o->path, m->path, (size_t)m->plen);
    int k = 0;
    for (uint32_t x = m->caps; x && k < 12; x &= x - 1) o->caps[k++] = (int8_t)CTZ(x);
    o->ncaps = (int8_t)k;
}

static int analyze(const Pos *root, int side, int ms, int max_depth, volatile int32_t *stop, ProgressFn cb, Result *res) {
    Search *S = (Search *)calloc(1, sizeof(Search));
    if (!S) return -1;
    S->tt = (TTE *)calloc((size_t)1 << TT_BITS, sizeof(TTE));
    if (!S->tt) { free(S); return -1; }
    S->stop = stop;
    memset(res, 0, sizeof *res);
    Move rm[MS];
    int n = gen(rm, root, side, 1);
    res->nmoves = n;
    if (n == 0) { res->score = -WIN; free(S->tt); free(S); return 0; }
    if (n == 1 && ms > 400) ms = 400;
    S->deadline = now_ms() + ms;
    uint64_t rh = hash_pos(root, side);
    Pos rp = *root; rp.h = rh;
    int best_score = 0, done = 0;
    for (int depth = 1; depth <= max_depth; depth++) {
        int alpha = -INF, ib = -1, is = -INF;
        for (int i = 0; i < n; i++) {
            Pos child = make(&rp, side, &rm[i]);
            int nd = (n == 1 && rm[i].caps) ? depth : depth - 1, v;
            if (i == 0) v = -search(S, 1, &child, -side, nd, -INF, -alpha);
            else {
                v = -search(S, 1, &child, -side, nd, -alpha - 1, -alpha);
                if (v > alpha && !S->aborted) v = -search(S, 1, &child, -side, nd, -INF, -alpha);
            }
            if (S->aborted) break;
            if (v > is) { is = v; ib = i; }
            if (v > alpha) alpha = v;
        }
        if (S->aborted) break;
        if (ib > 0) { Move t = rm[ib]; memmove(&rm[1], &rm[0], (size_t)ib * sizeof(Move)); rm[0] = t; }
        best_score = is; done = depth;
        if (cb) { OutMove o; to_out(&rm[0], &o); cb(depth, best_score, S->nodes, &o); }
        if ((best_score > WIN - 150 || best_score < -WIN + 150) && depth >= 2) break;
        if (now_ms() > S->deadline) break;
    }
    res->score = best_score; res->depth = done; res->nodes = S->nodes;
    to_out(&rm[0], &res->best);
    /* principal variation from the table */
    res->npv = 1; to_out(&rm[0], &res->pv[0]);
    Pos cur = make(&rp, side, &rm[0]);
    int cs = -side;
    for (int k = 1; k < 8; k++) {
        TTE *e = &S->tt[cur.h & ((1u << TT_BITS) - 1)];
        if (!(e->depth > 0 && e->key == (uint32_t)(cur.h >> 32) && e->move >= 0)) break;
        Move ms2[MS];
        int c = gen(ms2, &cur, cs, 1), f = -1;
        for (int i = 0; i < c; i++) if (ms2[i].from * 32 + ms2[i].to == e->move) { f = i; break; }
        if (f < 0) break;
        to_out(&ms2[f], &res->pv[res->npv++]);
        cur = make(&cur, cs, &ms2[f]);
        cs = -cs;
    }
    free(S->tt); free(S);
    return 0;
}

/* ------------------------------------------------------------------ exported API */
static Pos from_board(const int8_t *b) {
    Pos p = { 0, 0, 0, 0, 0 };
    for (int s = 0; s < 64; s++) {
        int v = b[s];
        if (!v) continue;
        int i = idx32(s >> 3, s & 7);
        if (i < 0) continue;
        uint32_t bit = 1u << i;
        if (v == 1) p.bm |= bit; else if (v == 2) p.bk |= bit; else if (v == -1) p.rm |= bit; else p.rk |= bit;
    }
    return p;
}

/* board64: 64 signed bytes, 1/2 black man/king, -1/-2 red man/king. side: 1 black, -1 red. */
KM_EXPORT int km_analyze(const int8_t *board64, int side, int ms, int max_depth,
                         volatile int32_t *stop, ProgressFn cb, Result *out) {
    km_init();
    Pos p = from_board(board64);
    return analyze(&p, side, ms, max_depth, stop, cb, out);
}

/* Perft helper so tests can check move generation natively. */
static uint64_t perft(Move (*buf)[MS], int ply, const Pos *p, int side, int d) {
    int n = gen(buf[ply], p, side, 0);
    if (d == 1) return (uint64_t)n;
    uint64_t t = 0;
    for (int i = 0; i < n; i++) { Pos q = make(p, side, &buf[ply][i]); t += perft(buf, ply + 1, &q, -side, d - 1); }
    return t;
}
KM_EXPORT uint64_t km_perft(const int8_t *board64, int side, int depth) {
    km_init();
    Pos p = from_board(board64);
    Move (*buf)[MS] = (Move (*)[MS])malloc(sizeof(Move) * MS * 40);
    if (!buf) return 0;
    uint64_t r = perft(buf, 0, &p, side, depth);
    free(buf);
    return r;
}
KM_EXPORT int km_abi(void) { return (int)(sizeof(Result) * 1000 + sizeof(OutMove)); }
