int loops(int seed, int bound) {
    int acc = seed + 1;
    int guard = bound;
    for (int i = 0; i < bound; i++) {
        acc = acc + 1;
        acc = acc + 2;
        acc = acc + 3;
        if (acc) acc = acc - 1;
        else acc = acc + 1;
        acc = acc + 5;
        acc = acc + 6;
        acc = acc + 7;
        if (acc) acc = acc - 1;
        else acc = acc + 1;
        acc = acc + 2;
        acc = acc + 3;
    }
    while (guard) guard = guard - 1;
    return acc + guard;
}
