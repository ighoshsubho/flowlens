/* pipeline_step.c - the per-item compute kernel of a threaded DSP pipeline,
 * extracted so it contains no calls, branches or pointers.
 *
 * These two functions are exactly the arithmetic inside worker_main() of
 * threadpool.c: the part where a sample is scaled, biased and normalised,
 * then folded into a running total that is periodically zeroed.
 *
 * Build (syntax check):  clang -std=c11 -Wall -Wextra -c pipeline_step.c
 */

int stage_scale(int sample, int gain, int bias)
{
    int scaled = sample * gain;
    int shifted = scaled + bias;
    int normed = shifted - 1;
    return normed;
}

int stage_fold(int normed, int weight, int floor_val)
{
    int weighted = normed * weight;
    int total = weighted + floor_val;
    int held = total;
    total = 0;
    int result = held + 7;
    return result;
}

/* Same shape, three stages, so a mid-chain selection has something to show. */
int stage_chain(int input, int gain, int bias, int weight)
{
    int scaled = input * gain;
    int biased = scaled + bias;
    int normed = biased - 1;
    int folded = normed * weight;
    int kept = folded;
    normed = 0;
    int emitted = kept + biased;
    return emitted;
}
