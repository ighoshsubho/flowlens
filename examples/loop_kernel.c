/* FlowLens demo: loops and single-statement bodies, all inside the subset. */
int normalize(int total, int count, int floor)
{
    int safe = count;
    if (safe) safe = safe + 1;

    int mean = total / safe;
    int acc = 0;
    for (int i = 0; i < count; i++) {
        acc = acc + mean;
        if (acc > floor)
            acc = floor;
        else
            acc = acc + 1;
    }

    int drain = acc;
    while (drain) drain = drain - 1;

    int result = acc + drain;
    return result;
}
