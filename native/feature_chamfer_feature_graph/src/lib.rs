use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::{HashMap, HashSet};

type V3 = [f64; 3];
type LinkMap = HashMap<(usize, usize), usize>;
type GeoSignature = Vec<Vec<[i64; 3]>>;

#[derive(Clone)]
struct Edge {
    id: usize,
    a: usize,
    b: usize,
    faces: Vec<usize>,
}

#[derive(Clone)]
struct Face {
    verts: Vec<usize>,
    edges: Vec<usize>,
    normal: V3,
    center: V3,
}

#[derive(Clone)]
struct Meta {
    patches: [usize; 2],
    convexity: i32,
}

#[derive(Clone)]
struct Candidate {
    a: usize,
    b: usize,
    angle: f64,
    miter: f64,
    shared_patches: Vec<usize>,
    allowed: bool,
    reason: Option<&'static str>,
}

#[derive(Clone)]
struct OptionRecord {
    selected: Vec<usize>,
    score: f64,
    signature: GeoSignature,
}

struct VertexRecord {
    vertex: usize,
    incident: Vec<usize>,
    candidates: Vec<Candidate>,
    options: Vec<OptionRecord>,
    degree_two: bool,
}

struct Strand {
    edges: Vec<usize>,
    vertices: Vec<usize>,
    cyclic: bool,
    endpoints: Vec<(usize, usize)>,
    common_patches: Vec<usize>,
    samples: Vec<V3>,
}

#[derive(Clone)]
struct GlobalScore {
    unsupported: i64,
    supported: i64,
    selected_count: i64,
    selected_weight: f64,
    exposed: i64,
    margin: f64,
    signature: GeoSignature,
}

fn add(a: V3, b: V3) -> V3 {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}
fn sub(a: V3, b: V3) -> V3 {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
fn mul(a: V3, s: f64) -> V3 {
    [a[0] * s, a[1] * s, a[2] * s]
}
fn dot(a: V3, b: V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn cross(a: V3, b: V3) -> V3 {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
fn length(a: V3) -> f64 {
    dot(a, a).sqrt()
}
fn normalize(a: V3) -> V3 {
    let size = length(a).max(1.0e-30);
    mul(a, 1.0 / size)
}
fn other(edge: &Edge, vertex: usize) -> usize {
    if edge.a == vertex { edge.b } else { edge.a }
}
fn rounded7(value: f64) -> f64 {
    (value * 10_000_000.0).round() / 10_000_000.0
}
fn point_key(point: V3) -> [i64; 3] {
    [
        (point[0] * 10_000_000.0).round() as i64,
        (point[1] * 10_000_000.0).round() as i64,
        (point[2] * 10_000_000.0).round() as i64,
    ]
}
fn connection_angle(vertices: &[V3], edges: &[Edge], vertex: usize, a: usize, b: usize) -> f64 {
    let x = normalize(sub(vertices[other(&edges[a], vertex)], vertices[vertex]));
    let y = normalize(sub(vertices[other(&edges[b], vertex)], vertices[vertex]));
    dot(x, y).clamp(-1.0, 1.0).acos().to_degrees()
}
fn miter_scale(angle: f64) -> f64 {
    1.0 / (angle.to_radians() * 0.5).sin().max(1.0e-6)
}
fn nav_candidate_key(vertex: usize, edge_a: usize, edge_b: usize) -> (usize, usize, usize) {
    (vertex, edge_a.min(edge_b), edge_a.max(edge_b))
}

fn face_patches(faces: &[Face], edges: &[Edge], sharp: &HashSet<usize>) -> (Vec<usize>, usize) {
    let mut patch = vec![usize::MAX; faces.len()];
    let mut count = 0;
    for seed in 0..faces.len() {
        if patch[seed] != usize::MAX {
            continue;
        }
        patch[seed] = count;
        let mut pending = vec![seed];
        while let Some(face) = pending.pop() {
            for &edge_id in &faces[face].edges {
                if sharp.contains(&edge_id) || edges[edge_id].faces.len() != 2 {
                    continue;
                }
                let adjacent = if edges[edge_id].faces[0] == face {
                    edges[edge_id].faces[1]
                } else {
                    edges[edge_id].faces[0]
                };
                if patch[adjacent] == usize::MAX {
                    patch[adjacent] = count;
                    pending.push(adjacent);
                }
            }
        }
        count += 1;
    }
    (patch, count)
}

fn enumerate_matchings(edge_ids: &[usize], candidates: &[Candidate]) -> Vec<OptionRecord> {
    fn visit(
        remaining: &mut Vec<usize>,
        candidates: &[Candidate],
        selected: &mut Vec<usize>,
        score: f64,
        out: &mut Vec<OptionRecord>,
    ) {
        if remaining.is_empty() {
            let mut stable = selected.clone();
            stable.sort_by_key(|index| {
                let candidate = &candidates[*index];
                (candidate.a, candidate.b)
            });
            out.push(OptionRecord {
                selected: stable,
                score,
                signature: Vec::new(),
            });
            return;
        }
        let edge = remaining.remove(0);
        visit(remaining, candidates, selected, score, out);
        let partners = remaining.clone();
        for partner in partners {
            if let Some(index) = candidates.iter().position(|candidate| {
                candidate.allowed
                    && ((candidate.a == edge && candidate.b == partner)
                        || (candidate.b == edge && candidate.a == partner))
            }) {
                let position = remaining.iter().position(|item| *item == partner).unwrap();
                remaining.remove(position);
                selected.push(index);
                visit(
                    remaining,
                    candidates,
                    selected,
                    score + candidates[index].angle,
                    out,
                );
                selected.pop();
                remaining.insert(position, partner);
            }
        }
        remaining.insert(0, edge);
    }

    let mut result = Vec::new();
    visit(
        &mut edge_ids.to_vec(),
        candidates,
        &mut Vec::new(),
        0.0,
        &mut result,
    );
    result.sort_by(|a, b| {
        b.score
            .total_cmp(&a.score)
            .then(b.selected.len().cmp(&a.selected.len()))
            .then(a.selected.cmp(&b.selected))
    });
    result
}

fn candidate_signature(
    candidate: &Candidate,
    vertex: usize,
    vertices: &[V3],
    edges: &[Edge],
) -> Vec<[i64; 3]> {
    let mut triple = vec![
        point_key(vertices[vertex]),
        point_key(vertices[other(&edges[candidate.a], vertex)]),
        point_key(vertices[other(&edges[candidate.b], vertex)]),
    ];
    triple.sort();
    triple
}

fn triangles(vertices: &[V3], faces: &[Face], indices: Option<&[[usize; 3]]>) -> Vec<[V3; 3]> {
    if let Some(indices) = indices {
        return indices
            .iter()
            .map(|triangle| {
                [
                    vertices[triangle[0]],
                    vertices[triangle[1]],
                    vertices[triangle[2]],
                ]
            })
            .collect();
    }
    let mut result = Vec::new();
    for face in faces {
        if face.verts.len() < 3 {
            continue;
        }
        let first = vertices[face.verts[0]];
        for index in 1..face.verts.len() - 1 {
            result.push([
                first,
                vertices[face.verts[index]],
                vertices[face.verts[index + 1]],
            ]);
        }
    }
    result
}

fn ray_triangle(origin: V3, direction: V3, triangle: &[V3; 3], epsilon: f64) -> Option<f64> {
    let edge_a = sub(triangle[1], triangle[0]);
    let edge_b = sub(triangle[2], triangle[0]);
    let p = cross(direction, edge_b);
    let determinant = dot(edge_a, p);
    if determinant.abs() <= epsilon {
        return None;
    }
    let inverse = 1.0 / determinant;
    let t = sub(origin, triangle[0]);
    let u = dot(t, p) * inverse;
    if u < -epsilon || u > 1.0 + epsilon {
        return None;
    }
    let q = cross(t, edge_a);
    let v = dot(direction, q) * inverse;
    if v < -epsilon || u + v > 1.0 + epsilon {
        return None;
    }
    let distance = dot(edge_b, q) * inverse;
    (distance > epsilon).then_some(distance)
}

fn point_triangle_distance(point: V3, triangle: &[V3; 3]) -> f64 {
    let a = triangle[0];
    let b = triangle[1];
    let c = triangle[2];
    let ab = sub(b, a);
    let ac = sub(c, a);
    let ap = sub(point, a);
    let d1 = dot(ab, ap);
    let d2 = dot(ac, ap);
    if d1 <= 0.0 && d2 <= 0.0 {
        return length(ap);
    }
    let bp = sub(point, b);
    let d3 = dot(ab, bp);
    let d4 = dot(ac, bp);
    if d3 >= 0.0 && d4 <= d3 {
        return length(bp);
    }
    let vc = d1 * d4 - d3 * d2;
    if vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0 {
        return length(sub(point, add(a, mul(ab, d1 / (d1 - d3)))));
    }
    let cp = sub(point, c);
    let d5 = dot(ab, cp);
    let d6 = dot(ac, cp);
    if d6 >= 0.0 && d5 <= d6 {
        return length(cp);
    }
    let vb = d5 * d2 - d1 * d6;
    if vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0 {
        return length(sub(point, add(a, mul(ac, d2 / (d2 - d6)))));
    }
    let va = d3 * d6 - d5 * d4;
    if va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0 {
        let bc = sub(c, b);
        return length(sub(
            point,
            add(b, mul(bc, (d4 - d3) / ((d4 - d3) + (d5 - d6)))),
        ));
    }
    let denom = 1.0 / (va + vb + vc);
    let nearest = add(a, add(mul(ab, vb * denom), mul(ac, vc * denom)));
    length(sub(point, nearest))
}

fn inside_closed_mesh(point: V3, tris: &[[V3; 3]], tolerance: f64) -> bool {
    let directions = [
        normalize([1.0, 0.371, 0.529]),
        normalize([-0.417, 1.0, 0.283]),
        normalize([0.233, -0.619, 1.0]),
    ];
    let advance = (tolerance * 0.25).max(1.0e-7);
    let mut votes = 0;
    for direction in directions {
        let mut distances: Vec<f64> = tris
            .iter()
            .filter_map(|triangle| ray_triangle(point, direction, triangle, advance * 0.1))
            .collect();
        distances.sort_by(f64::total_cmp);
        let mut unique = 0;
        let mut previous = f64::NEG_INFINITY;
        for distance in distances {
            if distance - previous > advance {
                unique += 1;
                previous = distance;
            }
        }
        votes += unique % 2;
    }
    votes >= 2
}

fn reconstruct_strands(
    sharp_ids: &[usize],
    vertices: &[V3],
    edges: &[Edge],
    meta: &HashMap<usize, Meta>,
    links: &LinkMap,
    clearance: f64,
) -> Vec<Strand> {
    let mut half_edges: Vec<(usize, usize)> = sharp_ids
        .iter()
        .flat_map(|edge_id| {
            let edge = &edges[*edge_id];
            [(edge.a, *edge_id), (edge.b, *edge_id)]
        })
        .collect();
    half_edges.sort_by_key(|(vertex, edge_id)| {
        let edge = &edges[*edge_id];
        let mut endpoints = [point_key(vertices[edge.a]), point_key(vertices[edge.b])];
        endpoints.sort();
        (point_key(vertices[*vertex]), endpoints)
    });
    let mut starts: Vec<(usize, usize)> = sharp_ids
        .iter()
        .map(|edge_id| {
            let edge = &edges[*edge_id];
            let start = edge.a.min(edge.b);
            (start, *edge_id)
        })
        .collect();
    starts.sort_by_key(|(_, edge_id)| *edge_id);
    let mut pending: Vec<(usize, usize)> = half_edges
        .into_iter()
        .filter(|key| !links.contains_key(key))
        .collect();
    pending.extend(starts);
    let mut remaining: HashSet<usize> = sharp_ids.iter().copied().collect();
    let mut strands = Vec::new();
    for (start, seed) in pending {
        if !remaining.contains(&seed) {
            continue;
        }
        let mut vertex = start;
        let mut current = seed;
        let mut ordered_edges = Vec::new();
        let mut ordered_vertices = vec![start];
        loop {
            if !remaining.remove(&current) {
                break;
            }
            ordered_edges.push(current);
            vertex = other(&edges[current], vertex);
            if vertex == start && links.get(&(vertex, current)) == Some(&seed) {
                break;
            }
            ordered_vertices.push(vertex);
            match links.get(&(vertex, current)) {
                Some(next) => current = *next,
                None => break,
            }
        }
        let cyclic =
            vertex == start && links.get(&(vertex, *ordered_edges.last().unwrap())) == Some(&seed);
        let endpoints = if cyclic {
            Vec::new()
        } else {
            vec![(start, seed), (vertex, *ordered_edges.last().unwrap())]
        };
        let mut common: HashSet<usize> = meta[&ordered_edges[0]].patches.into_iter().collect();
        for edge_id in ordered_edges.iter().skip(1) {
            common.retain(|patch| meta[edge_id].patches.contains(patch));
        }
        let mut common_patches: Vec<usize> = common.into_iter().collect();
        common_patches.sort();
        let mut samples = Vec::new();
        if !cyclic && clearance > 0.0 {
            let first_neighbor = other(&edges[seed], start);
            let last_edge = *ordered_edges.last().unwrap();
            let last_neighbor = other(&edges[last_edge], vertex);
            samples.push(add(
                vertices[start],
                mul(
                    normalize(sub(vertices[start], vertices[first_neighbor])),
                    clearance,
                ),
            ));
            samples.push(add(
                vertices[vertex],
                mul(
                    normalize(sub(vertices[vertex], vertices[last_neighbor])),
                    clearance,
                ),
            ));
        }
        strands.push(Strand {
            edges: ordered_edges,
            vertices: ordered_vertices,
            cyclic,
            endpoints,
            common_patches,
            samples,
        });
    }
    strands
}

fn score_is_better(candidate: &GlobalScore, current: &GlobalScore) -> bool {
    let left = (
        candidate.unsupported,
        candidate.supported,
        candidate.selected_count,
    );
    let right = (
        current.unsupported,
        current.supported,
        current.selected_count,
    );
    if left != right {
        return left > right;
    }
    let weight = candidate
        .selected_weight
        .total_cmp(&current.selected_weight);
    if !weight.is_eq() {
        return weight.is_gt();
    }
    if candidate.exposed != current.exposed {
        return candidate.exposed > current.exposed;
    }
    let margin = candidate.margin.total_cmp(&current.margin);
    if !margin.is_eq() {
        return margin.is_gt();
    }
    candidate.signature < current.signature
}

fn topology_score(
    links: &LinkMap,
    forbidden: &[(usize, usize, usize)],
    sharp_ids: &[usize],
    edges: &[Edge],
    meta: &HashMap<usize, Meta>,
) -> Option<(i64, i64)> {
    let mut remaining: HashSet<usize> = sharp_ids.iter().copied().collect();
    let mut unsupported = 0;
    let mut supported = 0;
    let mut pending: Vec<(usize, usize)> = sharp_ids
        .iter()
        .flat_map(|edge_id| {
            let edge = &edges[*edge_id];
            [(edge.a, *edge_id), (edge.b, *edge_id)]
        })
        .filter(|key| !links.contains_key(key))
        .collect();
    pending.extend(
        sharp_ids
            .iter()
            .map(|edge_id| (edges[*edge_id].a, *edge_id)),
    );
    for (start, seed) in pending {
        if !remaining.contains(&seed) {
            continue;
        }
        let mut vertex = start;
        let mut current = seed;
        let mut edge_count = 0usize;
        let mut common: HashSet<usize> = meta[&seed].patches.into_iter().collect();
        let mut cyclic = false;
        let mut last_edge = seed;
        loop {
            if !remaining.remove(&current) {
                break;
            }
            last_edge = current;
            edge_count += 1;
            common.retain(|patch| meta[&current].patches.contains(patch));
            vertex = other(&edges[current], vertex);
            if vertex == start && links.get(&(vertex, current)) == Some(&seed) {
                cyclic = true;
                break;
            }
            match links.get(&(vertex, current)) {
                Some(next) => current = *next,
                None => break,
            }
        }
        if !cyclic {
            let endpoints = [(start, seed), (vertex, last_edge)];
            if forbidden.iter().any(|(split_vertex, edge_a, edge_b)| {
                endpoints.contains(&(*split_vertex, *edge_a))
                    && endpoints.contains(&(*split_vertex, *edge_b))
            }) {
                return None;
            }
        }
        let turns = edge_count.saturating_sub(1) as i64;
        if common.is_empty() {
            unsupported += turns;
        } else {
            supported += turns;
        }
    }
    debug_assert!(remaining.is_empty());
    Some((-unsupported, supported))
}

fn score_combination(
    choice: &[usize],
    junctions: &[VertexRecord],
    fixed_links: &LinkMap,
    forbidden: &[(usize, usize, usize)],
    sharp_ids: &[usize],
    vertices: &[V3],
    edges: &[Edge],
    meta: &HashMap<usize, Meta>,
    tris: &[[V3; 3]],
    clearance: f64,
    containment_cache: &mut HashMap<[i64; 3], (bool, f64)>,
    evaluate_containment: bool,
) -> Option<(GlobalScore, LinkMap)> {
    let mut links = fixed_links.clone();
    let mut selected_count = 0;
    let mut selected_weight = 0.0;
    let mut signature = Vec::new();
    for (junction_index, option_index) in choice.iter().copied().enumerate() {
        let record = &junctions[junction_index];
        let option = &record.options[option_index];
        selected_count += option.selected.len() as i64;
        selected_weight += option.score;
        signature.extend(option.signature.clone());
        for candidate_index in &option.selected {
            let candidate = &record.candidates[*candidate_index];
            links.insert((record.vertex, candidate.a), candidate.b);
            links.insert((record.vertex, candidate.b), candidate.a);
        }
    }
    signature.sort();
    if !evaluate_containment {
        let (unsupported, supported) = topology_score(&links, forbidden, sharp_ids, edges, meta)?;
        return Some((
            GlobalScore {
                unsupported,
                supported,
                selected_count,
                selected_weight: rounded7(selected_weight),
                exposed: 0,
                margin: 0.0,
                signature,
            },
            links,
        ));
    }
    let strands = reconstruct_strands(
        sharp_ids,
        vertices,
        edges,
        meta,
        &links,
        if evaluate_containment { clearance } else { 0.0 },
    );
    for &(vertex, edge_a, edge_b) in forbidden {
        if strands.iter().any(|strand| {
            strand.endpoints.contains(&(vertex, edge_a))
                && strand.endpoints.contains(&(vertex, edge_b))
        }) {
            return None;
        }
    }
    let mut unsupported = 0;
    let mut supported = 0;
    for strand in &strands {
        let turns = strand.edges.len().saturating_sub(1) as i64;
        if strand.common_patches.is_empty() {
            unsupported += turns;
        } else {
            supported += turns;
        }
    }
    let tolerance = (clearance * 0.02).max(1.0e-6);
    let mut exposed = 0;
    let mut margin = 0.0;
    if evaluate_containment && clearance > 0.0 {
        for sample in strands.iter().flat_map(|strand| &strand.samples) {
            let result = *containment_cache
                .entry(point_key(*sample))
                .or_insert_with(|| {
                    let inside = inside_closed_mesh(*sample, tris, tolerance);
                    let nearest_distance = if inside {
                        tris.iter()
                            .map(|triangle| point_triangle_distance(*sample, triangle))
                            .fold(f64::INFINITY, f64::min)
                    } else {
                        0.0
                    };
                    (inside, nearest_distance)
                });
            if result.0 {
                margin += result.1;
            } else {
                exposed += 1;
            }
        }
    }
    Some((
        GlobalScore {
            unsupported: -unsupported,
            supported,
            selected_count,
            selected_weight: rounded7(selected_weight),
            exposed: -exposed,
            margin: rounded7(margin),
            signature,
        },
        links,
    ))
}

fn append_candidate<'py>(
    py: Python<'py>,
    list: &Bound<'py, PyList>,
    candidate: &Candidate,
    meta: &HashMap<usize, Meta>,
    degree_two: bool,
) -> PyResult<()> {
    let row = PyDict::new(py);
    row.set_item("edge_ids", (candidate.a, candidate.b))?;
    row.set_item("connection_angle", candidate.angle)?;
    row.set_item("miter_scale", candidate.miter)?;
    row.set_item("allowed", candidate.allowed)?;
    row.set_item("split_reason", candidate.reason)?;
    row.set_item(
        "weight",
        if candidate.allowed {
            candidate.angle
        } else {
            0.0
        },
    )?;
    if degree_two {
        let compatible = meta[&candidate.a].convexity == meta[&candidate.b].convexity
            && !candidate.shared_patches.is_empty();
        row.set_item("metadata_compatible", compatible)?;
        row.set_item(
            "warning",
            if candidate.allowed && !compatible {
                Some("SURFACE_CONTEXT_CHANGED_BUT_TOPOLOGY_CONTINUES")
            } else {
                None
            },
        )?;
        row.set_item(
            "patch_pairs",
            (meta[&candidate.a].patches, meta[&candidate.b].patches),
        )?;
        row.set_item(
            "convexities",
            (meta[&candidate.a].convexity, meta[&candidate.b].convexity),
        )?;
    } else {
        row.set_item("shared_patch_ids", &candidate.shared_patches)?;
    }
    list.append(row)
}

#[pyfunction]
#[pyo3(signature=(primitive,miter_scale_limit=1.5))]
fn solve_feature_graph<'py>(
    py: Python<'py>,
    primitive: &Bound<'py, PyDict>,
    miter_scale_limit: f64,
) -> PyResult<Bound<'py, PyDict>> {
    let vertices: Vec<V3> = primitive
        .get_item("vertices")?
        .ok_or_else(|| PyValueError::new_err("missing vertices"))?
        .extract()?;
    let edge_rows: Vec<(usize, usize, usize, Vec<usize>)> = primitive
        .get_item("edges")?
        .ok_or_else(|| PyValueError::new_err("missing edges"))?
        .extract()?;
    let face_rows: Vec<Bound<'py, PyDict>> = primitive
        .get_item("face_records")?
        .ok_or_else(|| PyValueError::new_err("missing face_records"))?
        .extract()?;
    let mut sharp_ids: Vec<usize> = primitive
        .get_item("sharp_edge_indices")?
        .ok_or_else(|| PyValueError::new_err("missing sharp_edge_indices"))?
        .extract()?;
    let edge_convexities: Option<Vec<i32>> = primitive
        .get_item("edge_convexities")?
        .map(|value| value.extract())
        .transpose()?;
    let triangle_indices: Option<Vec<[usize; 3]>> = primitive
        .get_item("triangles")?
        .map(|value| value.extract())
        .transpose()?;
    let frozen_containment: Option<Vec<(usize, usize, bool, f64)>> = primitive
        .get_item("containment_samples")?
        .map(|value| value.extract())
        .transpose()?;
    let candidate_metric_rows: Option<Vec<(usize, usize, usize, f64, f64)>> = primitive
        .get_item("candidate_metrics")?
        .map(|value| value.extract())
        .transpose()?;
    let candidate_metrics: HashMap<(usize, usize, usize), (f64, f64)> = candidate_metric_rows
        .unwrap_or_default()
        .into_iter()
        .map(|(vertex, edge_a, edge_b, angle, miter)| {
            (nav_candidate_key(vertex, edge_a, edge_b), (angle, miter))
        })
        .collect();
    let clearance: f64 = primitive
        .get_item("radius")?
        .ok_or_else(|| PyValueError::new_err("missing radius"))?
        .extract()?;
    let edges: Vec<Edge> = edge_rows
        .into_iter()
        .map(|(id, a, b, faces)| Edge { id, a, b, faces })
        .collect();
    if edges
        .iter()
        .enumerate()
        .any(|(index, edge)| index != edge.id)
    {
        return Err(PyValueError::new_err("edge ids must be dense"));
    }
    let mut faces = Vec::new();
    for face in face_rows {
        faces.push(Face {
            verts: face.get_item("vertex_indices")?.unwrap().extract()?,
            edges: face.get_item("edge_indices")?.unwrap().extract()?,
            normal: face.get_item("normal")?.unwrap().extract()?,
            center: face.get_item("center_median")?.unwrap().extract()?,
        });
    }
    sharp_ids.sort();
    let sharp: HashSet<usize> = sharp_ids.iter().copied().collect();
    if sharp.is_empty() {
        return Err(PyValueError::new_err("no sharp edges"));
    }
    for &edge_id in &sharp_ids {
        if edges[edge_id].faces.len() != 2 {
            return Err(PyValueError::new_err("sharp edge is not manifold"));
        }
    }

    let (patch, patch_count) = face_patches(&faces, &edges, &sharp);
    let mut meta = HashMap::new();
    let mut vertex_edges: HashMap<usize, Vec<usize>> = HashMap::new();
    for &edge_id in &sharp_ids {
        let edge = &edges[edge_id];
        let mut patches = [patch[edge.faces[0]], patch[edge.faces[1]]];
        patches.sort();
        let midpoint = mul(add(vertices[edge.a], vertices[edge.b]), 0.5);
        let face_a = edge.faces[0];
        let face_b = edge.faces[1];
        let direction_b = sub(faces[face_b].center, midpoint);
        let inward_b = sub(
            direction_b,
            mul(faces[face_b].normal, dot(direction_b, faces[face_b].normal)),
        );
        let sign = dot(faces[face_a].normal, inward_b);
        let computed_convexity = if sign.abs() <= 1.0e-7 {
            0
        } else if sign > 0.0 {
            -1
        } else {
            1
        };
        meta.insert(
            edge_id,
            Meta {
                patches,
                convexity: edge_convexities
                    .as_ref()
                    .map(|values| values[edge_id])
                    .unwrap_or(computed_convexity),
            },
        );
        vertex_edges.entry(edge.a).or_default().push(edge_id);
        vertex_edges.entry(edge.b).or_default().push(edge_id);
    }
    for incident in vertex_edges.values_mut() {
        incident.sort();
    }

    let mut records = Vec::new();
    let mut fixed_links = LinkMap::new();
    let mut forbidden = Vec::new();
    let mut junctions = Vec::new();
    let mut sorted_vertices: Vec<usize> = vertex_edges.keys().copied().collect();
    sorted_vertices.sort();
    for vertex in sorted_vertices.iter().copied() {
        let incident = vertex_edges[&vertex].clone();
        let degree_two = incident.len() == 2;
        let mut candidates = Vec::new();
        for left in 0..incident.len() {
            for right in left + 1..incident.len() {
                let a = incident[left];
                let b = incident[right];
                let (angle, miter) = candidate_metrics
                    .get(&nav_candidate_key(vertex, a, b))
                    .copied()
                    .unwrap_or_else(|| {
                        let angle = connection_angle(&vertices, &edges, vertex, a, b);
                        (angle, miter_scale(angle))
                    });
                let mut shared: Vec<usize> = meta[&a]
                    .patches
                    .into_iter()
                    .filter(|patch_id| meta[&b].patches.contains(patch_id))
                    .collect();
                shared.sort();
                shared.dedup();
                let compatible = meta[&a].convexity == meta[&b].convexity && !shared.is_empty();
                let reason = if degree_two {
                    (miter > miter_scale_limit).then_some("MITER_SCALE_EXCEEDED")
                } else {
                    match (!compatible, miter > miter_scale_limit) {
                        (true, true) => Some("SURFACE_CONTEXT_INCOMPATIBLE|MITER_SCALE_EXCEEDED"),
                        (true, false) => Some("SURFACE_CONTEXT_INCOMPATIBLE"),
                        (false, true) => Some("MITER_SCALE_EXCEEDED"),
                        (false, false) => None,
                    }
                };
                candidates.push(Candidate {
                    a,
                    b,
                    angle,
                    miter,
                    shared_patches: shared,
                    allowed: reason.is_none(),
                    reason,
                });
            }
        }
        let mut options = enumerate_matchings(&incident, &candidates);
        if degree_two {
            if candidates[0].allowed {
                fixed_links.insert((vertex, candidates[0].a), candidates[0].b);
                fixed_links.insert((vertex, candidates[0].b), candidates[0].a);
            } else {
                forbidden.push((vertex, candidates[0].a, candidates[0].b));
            }
        } else {
            let maximum_pairs = options
                .iter()
                .map(|item| item.selected.len())
                .max()
                .unwrap_or(0);
            let maximum_score = options
                .iter()
                .filter(|item| item.selected.len() == maximum_pairs)
                .map(|item| item.score)
                .fold(f64::NEG_INFINITY, f64::max);
            options.retain(|item| {
                item.selected.len() == maximum_pairs && (item.score - maximum_score).abs() <= 1.0e-7
            });
            for option in &mut options {
                option.signature = option
                    .selected
                    .iter()
                    .map(|index| {
                        candidate_signature(&candidates[*index], vertex, &vertices, &edges)
                    })
                    .collect();
                option.signature.sort();
            }
        }
        records.push(VertexRecord {
            vertex,
            incident,
            candidates,
            options,
            degree_two,
        });
    }
    for (record_index, record) in records.iter().enumerate() {
        if !record.degree_two {
            junctions.push(record_index);
        }
    }
    let search_space = junctions
        .iter()
        .try_fold(1usize, |total, record_index| {
            total.checked_mul(records[*record_index].options.len())
        })
        .unwrap_or(usize::MAX);
    if search_space > 65_536 {
        return Err(PyRuntimeError::new_err(format!(
            "Global Surface Patch matching search budget exceeded: {search_space}"
        )));
    }
    let junction_records: Vec<VertexRecord> = junctions
        .iter()
        .map(|index| VertexRecord {
            vertex: records[*index].vertex,
            incident: records[*index].incident.clone(),
            candidates: records[*index].candidates.clone(),
            options: records[*index].options.clone(),
            degree_two: false,
        })
        .collect();
    let tris = triangles(&vertices, &faces, triangle_indices.as_deref());
    let mut choice = vec![0usize; junction_records.len()];
    let mut topology_best: Option<GlobalScore> = None;
    let mut topology_ties: Vec<Vec<usize>> = Vec::new();
    let mut containment_cache: HashMap<[i64; 3], (bool, f64)> = frozen_containment
        .unwrap_or_default()
        .into_iter()
        .map(|(vertex, edge_id, inside, distance)| {
            let neighbor = other(&edges[edge_id], vertex);
            let point = add(
                vertices[vertex],
                mul(
                    normalize(sub(vertices[vertex], vertices[neighbor])),
                    clearance,
                ),
            );
            (point_key(point), (inside, distance))
        })
        .collect();
    loop {
        if let Some((score, _links)) = score_combination(
            &choice,
            &junction_records,
            &fixed_links,
            &forbidden,
            &sharp_ids,
            &vertices,
            &edges,
            &meta,
            &tris,
            clearance,
            &mut containment_cache,
            false,
        ) {
            let topology = (
                score.unsupported,
                score.supported,
                score.selected_count,
                score.selected_weight,
            );
            let replace = topology_best.as_ref().is_none_or(|current| {
                topology
                    > (
                        current.unsupported,
                        current.supported,
                        current.selected_count,
                        current.selected_weight,
                    )
            });
            let equal = topology_best.as_ref().is_some_and(|current| {
                topology
                    == (
                        current.unsupported,
                        current.supported,
                        current.selected_count,
                        current.selected_weight,
                    )
            });
            if replace {
                topology_best = Some(score);
                topology_ties.clear();
                topology_ties.push(choice.clone());
            } else if equal {
                topology_ties.push(choice.clone());
            }
        }
        if choice.is_empty() {
            break;
        }
        let mut position = choice.len();
        loop {
            if position == 0 {
                break;
            }
            position -= 1;
            choice[position] += 1;
            if choice[position] < junction_records[position].options.len() {
                break;
            }
            choice[position] = 0;
        }
        if position == 0 && choice[0] == 0 {
            break;
        }
    }
    let mut best: Option<(GlobalScore, LinkMap, Vec<usize>)> = None;
    let mut candidates = topology_ties;
    let mut exhaustive_fallback = false;
    loop {
        for choice in candidates.drain(..) {
            if let Some((score, links)) = score_combination(
                &choice,
                &junction_records,
                &fixed_links,
                &forbidden,
                &sharp_ids,
                &vertices,
                &edges,
                &meta,
                &tris,
                clearance,
                &mut containment_cache,
                true,
            ) {
                if best
                    .as_ref()
                    .is_none_or(|current| score_is_better(&score, &current.0))
                {
                    best = Some((score, links, choice));
                }
            }
        }
        if best.is_some() {
            break;
        }
        if exhaustive_fallback {
            break;
        }
        // The maximum topology bucket may contain only forbidden acute reconnects.
        // Fall back to complete scoring only for that rare guard case.
        for index in 0..search_space {
            let mut value = index;
            let mut choice = vec![0usize; junction_records.len()];
            for position in (0..choice.len()).rev() {
                let radix = junction_records[position].options.len();
                choice[position] = value % radix;
                value /= radix;
            }
            candidates.push(choice);
        }
        exhaustive_fallback = true;
    }
    let (global_score, best_links, best_choice) = best.ok_or_else(|| {
        PyRuntimeError::new_err("Global strand matching cannot keep an acute split disconnected")
    })?;
    let strands = reconstruct_strands(&sharp_ids, &vertices, &edges, &meta, &best_links, clearance);

    let py_matches = PyList::empty(py);
    for record in &records {
        let row = PyDict::new(py);
        row.set_item("vertex_index", record.vertex)?;
        if record.degree_two {
            row.set_item("vertex_coordinate", vertices[record.vertex])?;
        }
        row.set_item("incident_edge_ids", &record.incident)?;
        let py_candidates = PyList::empty(py);
        for candidate in &record.candidates {
            append_candidate(py, &py_candidates, candidate, &meta, record.degree_two)?;
        }
        row.set_item("pair_candidates", py_candidates)?;
        let selected_indices: Vec<usize> = if record.degree_two {
            if record.candidates[0].allowed {
                vec![0]
            } else {
                Vec::new()
            }
        } else {
            let junction_index = junction_records
                .iter()
                .position(|item| item.vertex == record.vertex)
                .unwrap();
            record.options[best_choice[junction_index]].selected.clone()
        };
        let selected_pairs: Vec<(usize, usize)> = selected_indices
            .iter()
            .map(|index| {
                let candidate = &record.candidates[*index];
                (candidate.a, candidate.b)
            })
            .collect();
        let used: HashSet<usize> = selected_pairs.iter().flat_map(|(a, b)| [*a, *b]).collect();
        row.set_item("selected_pairs", &selected_pairs)?;
        row.set_item(
            "unmatched_edge_ids",
            record
                .incident
                .iter()
                .filter(|edge_id| !used.contains(edge_id))
                .copied()
                .collect::<Vec<_>>(),
        )?;
        row.set_item(
            "ambiguity_margin",
            if record.degree_two && !selected_pairs.is_empty() {
                record.candidates[0].angle
            } else {
                0.0
            },
        )?;
        if record.degree_two {
            row.set_item("topology_priority_degree_two", true)?;
        } else {
            row.set_item("global_surface_patch_matching", true)?;
            row.set_item(
                "global_score",
                (
                    global_score.unsupported,
                    global_score.supported,
                    global_score.selected_count,
                    global_score.selected_weight,
                    global_score.exposed,
                    global_score.margin,
                ),
            )?;
            row.set_item("endpoint_containment_scoring", true)?;
            row.set_item("global_pairing_candidate_count", search_space)?;
            row.set_item("global_radius_sensitive", search_space > 1)?;
        }
        py_matches.append(row)?;
    }

    let groups = PyList::empty(py);
    for (pipe_id, strand) in strands.iter().enumerate() {
        let group = PyDict::new(py);
        group.set_item("pipe_id", pipe_id)?;
        group.set_item("edge_indices", &strand.edges)?;
        group.set_item("vertex_indices", &strand.vertices)?;
        group.set_item(
            "points",
            strand
                .vertices
                .iter()
                .map(|index| vertices[*index])
                .collect::<Vec<_>>(),
        )?;
        group.set_item("is_cyclic", strand.cyclic)?;
        group.set_item("patch_pair", meta[&strand.edges[0]].patches)?;
        group.set_item(
            "patch_pair_by_edge",
            strand
                .edges
                .iter()
                .map(|index| meta[index].patches)
                .collect::<Vec<_>>(),
        )?;
        group.set_item("convexity", meta[&strand.edges[0]].convexity)?;
        group.set_item(
            "convexity_by_edge",
            strand
                .edges
                .iter()
                .map(|index| meta[index].convexity)
                .collect::<Vec<_>>(),
        )?;
        let selected_vertices: Vec<usize> = strand
            .vertices
            .iter()
            .filter(|vertex| {
                vertex_edges[vertex].len() > 1
                    && strand
                        .edges
                        .iter()
                        .any(|edge_id| best_links.contains_key(&(**vertex, *edge_id)))
            })
            .copied()
            .collect();
        group.set_item("selected_pair_vertex_ids", selected_vertices)?;
        group.set_item(
            "start_feature_degree",
            vertex_edges[&strand.vertices[0]].len(),
        )?;
        let end_vertex = if strand.cyclic {
            strand.vertices[0]
        } else {
            *strand.vertices.last().unwrap()
        };
        group.set_item("end_feature_degree", vertex_edges[&end_vertex].len())?;
        groups.append(group)?;
    }

    let stats = PyDict::new(py);
    stats.set_item("sharp_edge_count", sharp.len())?;
    stats.set_item("surface_patch_count", patch_count)?;
    stats.set_item("pipe_group_count", strands.len())?;
    stats.set_item(
        "open_pipe_count",
        strands.iter().filter(|strand| !strand.cyclic).count(),
    )?;
    stats.set_item(
        "closed_pipe_count",
        strands.iter().filter(|strand| strand.cyclic).count(),
    )?;
    stats.set_item("topology_junction_count", junction_records.len())?;
    stats.set_item(
        "junction_vertex_indices",
        junction_records
            .iter()
            .map(|record| record.vertex)
            .collect::<Vec<_>>(),
    )?;
    stats.set_item("vertex_matching", py_matches)?;
    let output = PyDict::new(py);
    output.set_item("groups", groups)?;
    output.set_item("stats", stats)?;
    Ok(output)
}

#[pymodule]
fn _hst_feature_graph_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(solve_feature_graph, module)?)?;
    Ok(())
}
