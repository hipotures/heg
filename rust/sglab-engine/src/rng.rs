//! Deterministic fast PRNG (Xoshiro256++ seeded via SplitMix64).

#[derive(Clone, Debug)]
pub struct Rng {
    s: [u64; 4],
}

#[inline]
fn splitmix64(x: &mut u64) -> u64 {
    *x = x.wrapping_add(0x9e3779b97f4a7c15);
    let mut z = *x;
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
    z ^ (z >> 31)
}

impl Rng {
    pub fn new(mut seed: u64) -> Self {
        let s = [
            splitmix64(&mut seed),
            splitmix64(&mut seed),
            splitmix64(&mut seed),
            splitmix64(&mut seed),
        ];
        Self { s }
    }

    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        let result = self.s[0]
            .wrapping_add(self.s[3])
            .rotate_left(23)
            .wrapping_add(self.s[0]);
        let t = self.s[1] << 17;
        self.s[2] ^= self.s[0];
        self.s[3] ^= self.s[1];
        self.s[1] ^= self.s[2];
        self.s[0] ^= self.s[3];
        self.s[2] ^= t;
        self.s[3] = self.s[3].rotate_left(45);
        result
    }

    #[inline]
    pub fn next_f64(&mut self) -> f64 {
        // Uniform in [0, 1) with 53 bits of precision.
        ((self.next_u64() >> 11) as f64) * (1.0 / ((1u64 << 53) as f64))
    }

    #[inline]
    pub fn gen_range(&mut self, bound: usize) -> usize {
        debug_assert!(bound > 0);
        // Fast Lemire multiply-high unbiased range reduction.
        let b = bound as u64;
        let mut x = self.next_u64();
        let mut m = (x as u128) * (b as u128);
        let mut l = m as u64;
        if l < b {
            let t = b.wrapping_neg() % b;
            while l < t {
                x = self.next_u64();
                m = (x as u128) * (b as u128);
                l = m as u64;
            }
        }
        (m >> 64) as usize
    }

    pub fn shuffle<T>(&mut self, slice: &mut [T]) {
        for i in (1..slice.len()).rev() {
            let j = self.gen_range(i + 1);
            slice.swap(i, j);
        }
    }
}
