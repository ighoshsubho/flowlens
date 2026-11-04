/* worker_snippet.c - the hot path of a pthread worker, small enough to feed
 * the network (under 2 KB).  It is real threaded C: pointers, struct member
 * access, a call, a branch and a loop.
 *
 * FlowLens must NOT pretend to analyse this.  Every construct it cannot model
 * is supposed to show up in the anomaly counter.
 */

typedef struct {
    int sample;
    int gain;
    int bias;
} job_t;

typedef struct {
    int id;
    long partial;
    int errors;
} worker_t;

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
        if (take(&job) != 0) {
            poll++;
            continue;
        }
        int normed = normalise(&job);
        w->partial += normed;
        if (normed < 0)
            w->errors++;
    }
    return 0;
}
