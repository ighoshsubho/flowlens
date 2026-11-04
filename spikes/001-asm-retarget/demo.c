/* demo.c - deliberately full of constructs the C-side network cannot model:
 * pointers, a struct, an array, a loop, a call, a macro.  Used only to
 * measure what a retarget to assembly would look like.
 */
#include <stdio.h>
#include <stdlib.h>

#define SCALE 3

typedef struct {
    int n;
    int *data;
} buffer_t;

static int checksum(const buffer_t *b)
{
    int acc = 0;
    for (int i = 0; i < b->n; i++)
        acc += b->data[i] * SCALE;
    return acc;
}

static void fill(buffer_t *b, int seed)
{
    int v = seed;
    for (int i = 0; i < b->n; i++) {
        v = v * 7 + 3;
        b->data[i] = v;
    }
}

int main(void)
{
    buffer_t b;
    b.n = 8;
    b.data = malloc(sizeof(int) * (size_t)b.n);
    if (b.data == NULL)
        return 1;
    fill(&b, 11);
    int total = checksum(&b);
    printf("%d\n", total);
    free(b.data);
    return total != 0;
}
