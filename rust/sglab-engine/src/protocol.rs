//! Exact binary protocol v2 (`SGSC`/`SGSR`) drop-in server compatible with
//! `sglab.score_worker.PersistentScoreWorker` and `cpp/sglab_score_worker.cpp`.

use std::io::{self, BufReader, BufWriter, Read, Write};

use crate::cycles::{Cutoff, DfsScratch, evaluate_lengths};
use crate::graph::{BitGraph, MAX_ORDER};

const PROTOCOL_VERSION: u16 = 2;
const COMMAND_SCORE: u16 = 1;
const COMMAND_QUIT: u16 = 2;
const STATUS_OK: u16 = 0;
const STATUS_ERROR: u16 = 1;
const STATUS_DOMINATED: u16 = 2;
const MAX_PAYLOAD_BYTES: u32 = 64 * 1024;
const CUTOFF_FLAG: u32 = 1;
const LONGEST_FIRST_FLAG: u32 = 2;
const COMPACT_DOMINATED_FLAG: u32 = 4;
const KNOWN_FLAGS: u32 = 7;

fn read_exact_u16<R: Read>(r: &mut R) -> io::Result<u16> {
    let mut b = [0u8; 2];
    r.read_exact(&mut b)?;
    Ok(u16::from_le_bytes(b))
}

fn read_exact_u32<R: Read>(r: &mut R) -> io::Result<u32> {
    let mut b = [0u8; 4];
    r.read_exact(&mut b)?;
    Ok(u32::from_le_bytes(b))
}

fn read_exact_u64<R: Read>(r: &mut R) -> io::Result<u64> {
    let mut b = [0u8; 8];
    r.read_exact(&mut b)?;
    Ok(u64::from_le_bytes(b))
}

pub fn serve_protocol_v2() -> i32 {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut reader = BufReader::with_capacity(64 * 1024, stdin.lock());
    let mut writer = BufWriter::with_capacity(64 * 1024, stdout.lock());
    let mut scratch = DfsScratch::new();

    loop {
        let mut magic = [0u8; 4];
        match reader.read_exact(&mut magic) {
            Ok(()) => {}
            Err(err) if err.kind() == io::ErrorKind::UnexpectedEof => return 0,
            Err(_) => return 1,
        }
        if &magic != b"SGSC" {
            return 1;
        }
        let version = match read_exact_u16(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let command = match read_exact_u16(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let payload_bytes = match read_exact_u32(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        if version != PROTOCOL_VERSION || payload_bytes > MAX_PAYLOAD_BYTES {
            return 1;
        }
        if command == COMMAND_QUIT {
            return if payload_bytes == 0 { 0 } else { 1 };
        }
        if command != COMMAND_SCORE {
            return 1;
        }

        let request_id = match read_exact_u64(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let order = match read_exact_u16(&mut reader) {
            Ok(v) => v as usize,
            Err(_) => return 1,
        };
        let word_count = match read_exact_u16(&mut reader) {
            Ok(v) => v as usize,
            Err(_) => return 1,
        };
        let limit = match read_exact_u32(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let node_budget = match read_exact_u32(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let flags = match read_exact_u32(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let cutoff_total = match read_exact_u32(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let cutoff_weighted = match read_exact_u32(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let cutoff_simplicity = match read_exact_u32(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };
        let cutoff_inclusive = match read_exact_u32(&mut reader) {
            Ok(v) => v != 0,
            Err(_) => return 1,
        };
        let length_count = match read_exact_u16(&mut reader) {
            Ok(v) => v as usize,
            Err(_) => return 1,
        };
        let reserved = match read_exact_u16(&mut reader) {
            Ok(v) => v,
            Err(_) => return 1,
        };

        let expected_words = (order + 63) / 64;
        let expected_payload = (length_count * 2 + order * word_count * 8) as u32;
        let invalid = !(4..=MAX_ORDER).contains(&order)
            || word_count != expected_words
            || limit < 2
            || node_budget == 0
            || (flags & !KNOWN_FLAGS) != 0
            || ((flags & COMPACT_DOMINATED_FLAG) != 0 && (flags & CUTOFF_FLAG) == 0)
            || length_count > 64
            || reserved != 0
            || payload_bytes != expected_payload;

        if invalid {
            if write_response(&mut writer, request_id, STATUS_ERROR, &[]).is_err() {
                return 1;
            }
            continue;
        }

        let mut lengths = Vec::with_capacity(length_count);
        let mut bad_lengths = false;
        for _ in 0..length_count {
            let l = match read_exact_u16(&mut reader) {
                Ok(v) => v,
                Err(_) => return 1,
            };
            if l < 3 || (l as usize) > order || lengths.last().is_some_and(|&prev| l <= prev) {
                bad_lengths = true;
            }
            lengths.push(l);
        }

        let mut graph = BitGraph::empty(order);
        for row in 0..order {
            let lo = match read_exact_u64(&mut reader) {
                Ok(v) => v as u128,
                Err(_) => return 1,
            };
            let hi = if word_count == 2 {
                match read_exact_u64(&mut reader) {
                    Ok(v) => (v as u128) << 64,
                    Err(_) => return 1,
                }
            } else {
                0u128
            };
            graph.rows[row] = lo | hi;
        }

        if bad_lengths {
            if write_response(&mut writer, request_id, STATUS_ERROR, &[]).is_err() {
                return 1;
            }
            continue;
        }

        let cutoff = if (flags & CUTOFF_FLAG) != 0 {
            Some(Cutoff {
                total: cutoff_total,
                weighted: cutoff_weighted,
                simplicity: cutoff_simplicity,
                inclusive: cutoff_inclusive,
            })
        } else {
            None
        };
        let longest_first = (flags & LONGEST_FIRST_FLAG) != 0;
        let (dominated, mut results) = evaluate_lengths(
            &graph,
            &lengths,
            limit - 1,
            node_budget,
            cutoff,
            longest_first,
            &mut scratch,
            true,
        );

        let status = if dominated {
            STATUS_DOMINATED
        } else {
            STATUS_OK
        };
        if dominated && (flags & COMPACT_DOMINATED_FLAG) != 0 {
            results.clear();
        } else {
            results.sort_by_key(|r| r.length);
        }

        if write_response(&mut writer, request_id, status, &results).is_err() {
            return 1;
        }
    }
}

fn write_response<W: Write>(
    writer: &mut W,
    request_id: u64,
    status: u16,
    results: &[crate::cycles::CountResult],
) -> io::Result<()> {
    writer.write_all(b"SGSR")?;
    writer.write_all(&PROTOCOL_VERSION.to_le_bytes())?;
    writer.write_all(&status.to_le_bytes())?;
    writer.write_all(&request_id.to_le_bytes())?;
    writer.write_all(&(results.len() as u16).to_le_bytes())?;
    writer.write_all(&0u16.to_le_bytes())?;
    writer.write_all(&((results.len() * 24) as u32).to_le_bytes())?;
    for r in results {
        writer.write_all(&r.length.to_le_bytes())?;
        writer.write_all(&[if r.complete { 1u8 } else { 0u8 }, 0u8])?;
        writer.write_all(&r.count.to_le_bytes())?;
        writer.write_all(&r.nodes.to_le_bytes())?;
        writer.write_all(&r.elapsed_ns.to_le_bytes())?;
    }
    writer.flush()
}
