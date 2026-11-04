/* threadpool.c - bounded-queue pthread pool with per-thread partial sums and
 * a barrier-synchronised reduction round.
 *
 * This is the kind of "advanced multithreading" C that FlowLens explicitly
 * does NOT model: threads, mutexes, condvars, atomics, a barrier, pointers,
 * a struct-based job queue, branches and loops.  It is here as a test of the
 * *honesty* path: the network must report it as unsupported instead of
 * inventing an information flow.
 *
 * Build:  clang -std=c11 -O2 -Wall -Wextra -pthread threadpool.c -o threadpool
 */

/* macOS hides pthread_barrier_t unless an X/Open level is requested. */
#define _XOPEN_SOURCE 700

#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NTHREADS 4
#define QCAP 64
#define NJOBS 32

typedef struct {
    int sample;
    int gain;
    int bias;
} job_t;

typedef struct {
    job_t ring[QCAP];
    unsigned head;
    unsigned tail;
    unsigned count;
    int closed;
    pthread_mutex_t mu;
    pthread_cond_t not_empty;
    pthread_cond_t not_full;
} queue_t;

/* Darwin's pthread.h has no pthread_barrier_t, so the pool carries its own
 * reusable sense-reversing barrier built from a mutex and a condvar. */
typedef struct {
    pthread_mutex_t mu;
    pthread_cond_t go;
    unsigned arrived;
    unsigned n;
    unsigned gen;
} barrier_t;

static void barrier_init(barrier_t *b, unsigned n)
{
    pthread_mutex_init(&b->mu, NULL);
    pthread_cond_init(&b->go, NULL);
    b->arrived = 0;
    b->n = n;
    b->gen = 0;
}

static void barrier_wait(barrier_t *b)
{
    pthread_mutex_lock(&b->mu);
    unsigned gen = b->gen;
    b->arrived++;
    if (b->arrived == b->n) {
        b->arrived = 0;
        b->gen++;
        pthread_cond_broadcast(&b->go);
    } else {
        while (gen == b->gen)
            pthread_cond_wait(&b->go, &b->mu);
    }
    pthread_mutex_unlock(&b->mu);
}

static void barrier_destroy(barrier_t *b)
{
    pthread_mutex_destroy(&b->mu);
    pthread_cond_destroy(&b->go);
}

typedef struct {
    queue_t *q;
    barrier_t *bar;
    int id;
    long partial;      /* this thread's accumulator */
    long grand;        /* written by the elected folder */
    int normed_last;   /* last normalised value this thread produced */
    int errors;
} worker_t;

static void queue_init(queue_t *q)
{
    memset(q, 0, sizeof(*q));
    pthread_mutex_init(&q->mu, NULL);
    pthread_cond_init(&q->not_empty, NULL);
    pthread_cond_init(&q->not_full, NULL);
}

static int queue_push(queue_t *q, job_t job)
{
    pthread_mutex_lock(&q->mu);
    while (q->count == QCAP && !q->closed)
        pthread_cond_wait(&q->not_full, &q->mu);
    if (q->closed) {
        pthread_mutex_unlock(&q->mu);
        return -1;
    }
    q->ring[q->tail] = job;
    q->tail = (q->tail + 1u) % QCAP;
    q->count++;
    pthread_cond_signal(&q->not_empty);
    pthread_mutex_unlock(&q->mu);
    return 0;
}

static int queue_pop(queue_t *q, job_t *out)
{
    pthread_mutex_lock(&q->mu);
    while (q->count == 0 && !q->closed)
        pthread_cond_wait(&q->not_empty, &q->mu);
    if (q->count == 0 && q->closed) {
        pthread_mutex_unlock(&q->mu);
        return -1;
    }
    *out = q->ring[q->head];
    q->head = (q->head + 1u) % QCAP;
    q->count--;
    pthread_cond_signal(&q->not_full);
    pthread_mutex_unlock(&q->mu);
    return 0;
}

static void queue_close(queue_t *q)
{
    pthread_mutex_lock(&q->mu);
    q->closed = 1;
    pthread_cond_broadcast(&q->not_empty);
    pthread_cond_broadcast(&q->not_full);
    pthread_mutex_unlock(&q->mu);
}

/* the per-item kernel: this arithmetic is the part pipeline_step.c isolates */
static int normalise(job_t *job)
{
    int scaled = job->sample * job->gain;
    int shifted = scaled + job->bias;
    int normed = shifted - 1;
    return normed;
}

static void *worker_main(void *arg)
{
    worker_t *w = (worker_t *)arg;
    job_t job;
    int poll = 0;

    while (poll < 4) {
        if (queue_pop(w->q, &job) != 0) {
            if (++poll > 2)
                break;
            continue;
        }
        int normed = normalise(&job);
        w->normed_last = normed;
        w->partial += normed;
        if (normed < 0)
            w->errors++;
    }

    barrier_wait(w->bar);

    if (w->id == 0) {
        for (int i = 0; i < NTHREADS; i++) {
            worker_t *peer = w + i;
            w->grand += peer->partial;
        }
    }
    barrier_wait(w->bar);
    return NULL;
}

int main(void)
{
    pthread_t tid[NTHREADS];
    worker_t workers[NTHREADS];
    queue_t q;
    barrier_t bar;
    atomic_int produced = 0;

    queue_init(&q);
    barrier_init(&bar, NTHREADS);

    for (int i = 0; i < NTHREADS; i++) {
        workers[i].q = &q;
        workers[i].bar = &bar;
        workers[i].id = i;
        workers[i].partial = 0;
        workers[i].grand = 0;
        workers[i].errors = 0;
        if (pthread_create(&tid[i], NULL, worker_main, &workers[i]) != 0) {
            fprintf(stderr, "pthread_create failed: %d\n", i);
            return 1;
        }
    }

    for (int i = 0; i < NJOBS; i++) {
        job_t job = { .sample = i * 3 + 1, .gain = 2, .bias = i % 5 };
        if (queue_push(&q, job) != 0)
            break;
        atomic_fetch_add(&produced, 1);
    }

    queue_close(&q);

    for (int i = 0; i < NTHREADS; i++)
        pthread_join(tid[i], NULL);

    long sum = 0;
    for (int i = 0; i < NTHREADS; i++)
        sum += workers[i].partial;

    printf("jobs=%d grand=%ld checksum=%ld errors=%d\n",
           atomic_load(&produced), workers[0].grand, sum,
           workers[0].errors + workers[1].errors);

    barrier_destroy(&bar);
    pthread_mutex_destroy(&q.mu);
    pthread_cond_destroy(&q.not_empty);
    pthread_cond_destroy(&q.not_full);
    return 0;
}
