"""Offline topology-first hole-grid experiment.

This module is deliberately not imported by the photo-route application.  It
keeps image evidence separate from inferred grid positions and never assumes a
20 x 30 wall.  The affine model is only an experiment-A baseline; later
continuous warp experiments can consume its observed correspondences.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import math
from typing import Iterable

import cv2
import numpy as np


MIN_OBSERVED_APPEARANCE = .30


@dataclass(frozen=True)
class HoleCandidate:
    x: float
    y: float
    appearance: float
    sources: tuple[str, ...] = ()
    radius: float = 0.0


def _normalise(values: np.ndarray) -> np.ndarray:
    low, high = np.percentile(values, (5, 99.5))
    if high <= low + 1e-9:
        return np.zeros_like(values, dtype=np.float32)
    return np.clip((values - low) / (high - low), 0, 1).astype(np.float32)


def _peaks(response: np.ndarray, source: str, minimum_distance: int) -> list[HoleCandidate]:
    size = max(3, minimum_distance * 2 + 1)
    maximum = cv2.dilate(response, np.ones((size, size), np.uint8))
    threshold = max(.2, float(np.percentile(response, 91)))
    mask = ((response >= maximum - 1e-6) & (response >= threshold)).astype(np.uint8)
    count, labels, stats, centres = cv2.connectedComponentsWithStats(mask)
    result = []
    for label, (x, y) in enumerate(centres[1:count], 1):
        left, top, width, height = (int(value) for value in stats[label, :4])
        local_response = response[top:top+height, left:left+width]
        local_labels = labels[top:top+height, left:left+width]
        strongest = int(np.argmax(np.where(local_labels == label, local_response, -1)))
        local_y, local_x = np.unravel_index(strongest, local_response.shape)
        x, y = float(left+local_x), float(top+local_y)
        px, py = int(round(x)), int(round(y))
        result.append(HoleCandidate(float(x), float(y), float(response[py, px]), (source,)))
    return result


def _merge_candidates(candidates: Iterable[HoleCandidate], distance: float) -> list[HoleCandidate]:
    merged: list[HoleCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.appearance, reverse=True):
        match = next((index for index, previous in enumerate(merged)
                      if math.hypot(previous.x-candidate.x, previous.y-candidate.y) <= distance), None)
        if match is None:
            merged.append(candidate)
            continue
        previous = merged[match]
        total = previous.appearance + candidate.appearance
        sources = tuple(sorted(set(previous.sources + candidate.sources)))
        if total <= 1e-9:
            total = 2.0
            previous_weight = candidate_weight = 1.0
        else:
            previous_weight, candidate_weight = previous.appearance, candidate.appearance
        merged[match] = HoleCandidate(
            (previous.x*previous_weight + candidate.x*candidate_weight) / total,
            (previous.y*previous_weight + candidate.y*candidate_weight) / total,
            max(previous.appearance, candidate.appearance), sources,
            max(previous.radius, candidate.radius),
        )
    return merged


def _rerank_appearance(image: np.ndarray, gray: np.ndarray, candidates: list[HoleCandidate],
                       scale: int) -> list[HoleCandidate]:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV) if image.ndim == 3 else None
    radius = max(3, 4*scale)
    yy, xx = np.mgrid[-radius:radius+1, -radius:radius+1]
    centre_mask = xx*xx+yy*yy <= max(1, scale)**2
    ring_mask = ((2*scale)**2 <= xx*xx+yy*yy) & (xx*xx+yy*yy <= radius*radius)
    ranked = []
    for candidate in candidates:
        x, y = int(round(candidate.x)), int(round(candidate.y))
        if x-radius < 0 or y-radius < 0 or x+radius >= gray.shape[1] or y+radius >= gray.shape[0]:
            continue
        patch = gray[y-radius:y+radius+1, x-radius:x+radius+1]
        centre = float(np.mean(patch[centre_mask]))
        ring = float(np.median(patch[ring_mask]))
        contrast = float(np.clip((ring-centre)/32, 0, 1))
        source_consistency = min(1.0, len(candidate.sources)/3)
        score = .58*contrast + .24*source_consistency + .18*candidate.appearance
        if hsv is not None:
            saturation = float(np.median(hsv[y-radius:y+radius+1, x-radius:x+radius+1, 1][centre_mask]))
            score *= 1-.8*float(np.clip((saturation-55)/120, 0, 1))
        ranked.append(HoleCandidate(candidate.x, candidate.y, float(np.clip(score, 0, 1)),
                                    candidate.sources, candidate.radius))
    return ranked


def generate_hole_candidates(image: np.ndarray, roi: tuple[int, int, int, int] | None = None,
                             maximum: int = 1600) -> list[HoleCandidate]:
    """Generate high-recall LoG/DoG/ellipse candidates inside an explicit wall ROI."""
    if image is None or image.ndim not in (2, 3) or min(image.shape[:2]) < 64:
        raise ValueError('需要有效岩壁图像')
    height, width = image.shape[:2]
    x0, y0, rw, rh = roi or (0, 0, width, height)
    if x0 < 0 or y0 < 0 or rw <= 0 or rh <= 0 or x0+rw > width or y0+rh > height:
        raise ValueError('墙面 ROI 越界')
    crop = image[y0:y0+rh, x0:x0+rw]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
    gray = gray.astype(np.float32)
    scale = max(1, round(min(rw, rh) / 500))
    candidates: list[HoleCandidate] = []
    for small, large, name in ((.7*scale, 2.0*scale, 'dog-small'),
                               (1.2*scale, 3.5*scale, 'dog-large')):
        response = cv2.GaussianBlur(gray, (0, 0), large) - cv2.GaussianBlur(gray, (0, 0), small)
        candidates.extend(_peaks(_normalise(response), name, max(2, 2*scale)))
    log_response = np.maximum(cv2.Laplacian(cv2.GaussianBlur(gray, (0, 0), 1.2*scale), cv2.CV_32F), 0)
    candidates.extend(_peaks(_normalise(log_response), 'log', max(2, 2*scale)))

    # Ellipse evidence is intentionally permissive: topology, not this detector,
    # decides whether a dark round object belongs to the lattice.
    local = cv2.GaussianBlur(gray, (0, 0), 5*scale) - gray
    binary = (local > max(5.0, float(np.percentile(local, 87)))).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        area = cv2.contourArea(contour)
        if len(contour) < 5 or not 3 <= area <= max(1200, rw*rh*.001):
            continue
        (_, _), (major, minor), _ = cv2.fitEllipse(contour)
        if min(major, minor) <= 0 or max(major, minor) / min(major, minor) > 2.5:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        strength = float(np.clip(local[int(round(cy)), int(round(cx))] / 45, .05, 1))
        candidates.append(HoleCandidate(cx, cy, strength, ('ellipse',), radius))

    merged = _merge_candidates(candidates, max(2.0, 2.5*scale))
    merged = _rerank_appearance(crop, gray, merged, scale)
    result = [HoleCandidate(c.x+x0, c.y+y0, c.appearance, c.sources, c.radius) for c in merged]
    return sorted(result, key=lambda item: item.appearance, reverse=True)[:maximum]


def _delaunay_edges(points: np.ndarray, shape: tuple[int, int] | None) -> set[tuple[int, int]]:
    if len(points) < 3:
        return set()
    if shape:
        height, width = shape
        offset = np.zeros(2)
        bounds = (0, 0, width, height)
    else:
        minimum = points.min(axis=0) - 2
        maximum = points.max(axis=0) + 2
        offset = minimum
        bounds = (0, 0, max(2, int(math.ceil(maximum[0]-minimum[0]))),
                  max(2, int(math.ceil(maximum[1]-minimum[1]))))
    shifted = points - offset
    subdivision = cv2.Subdiv2D(bounds)
    for x, y in shifted:
        subdivision.insert((float(np.clip(x, 1, bounds[2]-1)), float(np.clip(y, 1, bounds[3]-1))))
    edges: set[tuple[int, int]] = set()
    for triangle in subdivision.getTriangleList():
        vertices = np.asarray(triangle, dtype=float).reshape(3, 2)
        ids = [int(np.argmin(np.sum((shifted-v)**2, axis=1))) for v in vertices]
        for a, b in ((ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])):
            if a != b:
                edges.add(tuple(sorted((a, b))))
    return edges


def _assign(points: np.ndarray, scores: np.ndarray, origin: np.ndarray, basis: np.ndarray,
            tolerance: float) -> tuple[list[dict], list[int], float]:
    if abs(np.linalg.det(basis)) < 1e-8:
        return [], list(range(len(points))), -math.inf
    fractional = (points-origin) @ np.linalg.inv(basis)
    integer = np.rint(fractional).astype(int)
    residual = np.linalg.norm((fractional-integer), axis=1)
    accepted = np.flatnonzero((residual <= tolerance) & (scores >= MIN_OBSERVED_APPEARANCE))
    cells: dict[tuple[int, int], int] = {}
    rejected: set[int] = set(range(len(points)))
    assignments = []
    collisions = 0
    for index in sorted(accepted, key=lambda i: (residual[i], -scores[i])):
        cell = tuple(int(v) for v in integer[index])
        if cell in cells:
            collisions += 1
            continue
        cells[cell] = int(index)
        rejected.discard(int(index))
        assignments.append({'candidate_index': int(index), 'grid': cell,
                            'residual': float(residual[index])})
    if len(assignments) < 4:
        return assignments, sorted(rejected), -math.inf
    coords = np.asarray([item['grid'] for item in assignments], dtype=float)
    span = np.ptp(coords, axis=0)
    neighbours = sum((int(x+1), int(y)) in cells or (int(x), int(y+1)) in cells
                     for x, y in coords)
    evidence = sum(scores[item['candidate_index']] for item in assignments)
    mean_error = np.mean([item['residual'] for item in assignments])
    cell_area = float(np.prod(span+1))
    density = len(assignments) / max(1.0, cell_area)
    score = evidence + .3*len(assignments) + .6*neighbours + .08*math.sqrt(max(0, span.prod()))
    score -= 1.2*len(assignments)*(1-density)
    score -= 2.5*mean_error*len(assignments) + .8*collisions
    return assignments, sorted(rejected), float(score)


def _refine(points: np.ndarray, assignments: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    ids = np.asarray([item['candidate_index'] for item in assignments])
    grid = np.asarray([item['grid'] for item in assignments], dtype=float)
    design = np.column_stack((np.ones(len(grid)), grid))
    parameters, _, _, _ = np.linalg.lstsq(design, points[ids], rcond=None)
    return parameters[0], parameters[1:]


def _canonicalize(origin: np.ndarray, basis: np.ndarray,
                  assignments: list[dict]) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Remove axis-swap, sign and integer-origin aliases of the same lattice."""
    basis = basis.copy()
    grid = np.asarray([item['grid'] for item in assignments], dtype=int)
    if abs(basis[0, 0]) < abs(basis[1, 0]):
        basis = basis[[1, 0]]
        grid = grid[:, [1, 0]]
    if basis[0, 0] < 0:
        basis[0] *= -1
        grid[:, 0] *= -1
    if basis[1, 1] < 0:
        basis[1] *= -1
        grid[:, 1] *= -1
    minimum = grid.min(axis=0)
    origin = origin + minimum @ basis
    grid -= minimum
    normalised = [dict(item, grid=tuple(int(value) for value in cell))
                  for item, cell in zip(assignments, grid)]
    return origin, basis, normalised


def _project(matrix: np.ndarray, coordinates: np.ndarray) -> np.ndarray:
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, 2)
    homogeneous = np.column_stack((coordinates, np.ones(len(coordinates)))) @ matrix.T
    denominator = homogeneous[:, 2:3]
    if np.any(np.abs(denominator) < 1e-9):
        raise ValueError('单应性在有效网格内产生无效坐标')
    return homogeneous[:, :2] / denominator


def _fit_homography(points: np.ndarray, assignments: list[dict], spacing: float) -> tuple[np.ndarray, str]:
    ids = np.asarray([item['candidate_index'] for item in assignments])
    grid = np.asarray([item['grid'] for item in assignments], dtype=np.float64)
    method = getattr(cv2, 'USAC_MAGSAC', cv2.RANSAC)
    name = 'usac-magsac' if method != cv2.RANSAC else 'ransac-fallback'
    matrix, _ = cv2.findHomography(grid, points[ids], method, max(1.5, spacing*.12))
    if matrix is None or abs(np.linalg.det(matrix)) < 1e-10:
        raise ValueError('无法形成稳定的全局单应性')
    return matrix, name


def _assign_homography(points: np.ndarray, scores: np.ndarray, matrix: np.ndarray,
                       tolerance: float) -> tuple[list[dict], list[int], float]:
    inverse = np.linalg.inv(matrix)
    fractional = _project(inverse, points)
    integer = np.rint(fractional).astype(int)
    predicted = _project(matrix, integer)
    # Convert pixel error to local grid-spacing units so perspective does not
    # give near-camera candidates a looser gate than distant candidates.
    predicted_x = _project(matrix, integer + [1, 0])
    predicted_y = _project(matrix, integer + [0, 1])
    spacing = np.sqrt(np.linalg.norm(predicted_x-predicted, axis=1) *
                      np.linalg.norm(predicted_y-predicted, axis=1))
    residual = np.linalg.norm(points-predicted, axis=1) / np.maximum(spacing, 1e-6)
    accepted = np.flatnonzero((residual <= tolerance) & (scores >= MIN_OBSERVED_APPEARANCE))
    cells: dict[tuple[int, int], int] = {}
    rejected: set[int] = set(range(len(points)))
    assignments = []
    collisions = 0
    for index in sorted(accepted, key=lambda i: (residual[i], -scores[i])):
        cell = tuple(int(value) for value in integer[index])
        if cell in cells:
            collisions += 1
            continue
        cells[cell] = int(index)
        rejected.discard(int(index))
        assignments.append({'candidate_index': int(index), 'grid': cell,
                            'residual': float(residual[index])})
    evidence = sum(scores[item['candidate_index']] for item in assignments)
    neighbours = sum((x+1, y) in cells or (x, y+1) in cells for x, y in cells)
    error = sum(item['residual'] for item in assignments)
    coordinates = np.asarray(list(cells), dtype=float)
    cell_area = float(np.prod(np.ptp(coordinates, axis=0)+1)) if len(coordinates) else 1.0
    density = len(assignments) / max(1.0, cell_area)
    value = evidence + .3*len(assignments) + .6*neighbours - 2.5*error - .8*collisions
    value -= 1.2*len(assignments)*(1-density)
    return assignments, sorted(rejected), float(value)


def _continuous_model(points: np.ndarray, assignments: list[dict], matrix: np.ndarray,
                      method: str) -> dict:
    ids = np.asarray([item['candidate_index'] for item in assignments])
    grid = np.asarray([item['grid'] for item in assignments], dtype=float)
    raw = points[ids] - _project(matrix, grid)
    norms = np.linalg.norm(raw, axis=1)
    median = float(np.median(norms))
    scale = max(1.0, 1.4826*float(np.median(np.abs(norms-median))))
    projected = _project(matrix, grid)
    local_spacing = np.sqrt(np.linalg.norm(_project(matrix, grid+[1, 0])-projected, axis=1) *
                            np.linalg.norm(_project(matrix, grid+[0, 1])-projected, axis=1))
    cap = max(1.0, .08*float(np.median(local_spacing)))
    weights = np.minimum(1.0, np.minimum(1.5*scale, cap)/np.maximum(norms, 1e-9))
    residuals = raw * weights[:, None]
    return {'homography': matrix.tolist(), 'robust_method': method,
            'residual_kernel': 'gaussian-local', 'residual_bandwidth_cells': 4.0,
            'control_grid': grid.tolist(), 'control_residual_px': residuals.tolist(),
            'robust_scale_px': scale, 'residual_cap_px': cap}


def _map_grid_points(model: dict, coordinates: np.ndarray) -> np.ndarray:
    grids = np.asarray(coordinates, dtype=float).reshape(-1, 2)
    points = _project(np.asarray(model['homography'], dtype=float), grids)
    controls = np.asarray(model.get('control_grid', []), dtype=float)
    residuals = np.asarray(model.get('control_residual_px', []), dtype=float)
    if len(controls):
        bandwidth = float(model.get('residual_bandwidth_cells', 2.5))
        for start in range(0, len(grids), 512):
            block = grids[start:start+512]
            squared = np.sum((block[:, None, :]-controls[None, :, :])**2, axis=2)
            count = min(12, len(controls))
            nearest = np.argpartition(squared, count-1, axis=1)[:, :count]
            selected = np.take_along_axis(squared, nearest, axis=1)
            weights = np.exp(-.5*selected/(bandwidth*bandwidth))
            weighted = np.sum(residuals[nearest]*weights[:, :, None], axis=1)
            points[start:start+len(block)] += weighted/np.maximum(weights.sum(axis=1)[:, None], 1e-9)
    return points


def map_grid_point(model: dict, coordinate: tuple[float, float]) -> tuple[float, float]:
    point = _map_grid_points(model, np.asarray(coordinate, dtype=float))[0]
    return float(point[0]), float(point[1])


def _foldover_diagnostics(model: dict, assignments: list[dict]) -> dict:
    grid = np.asarray([item['grid'] for item in assignments], dtype=int)
    minimum, maximum = grid.min(axis=0), grid.max(axis=0)
    width, height = maximum-minimum
    cell_count = int(width*height)
    if cell_count > max(5000, 4*len(assignments)):
        return {'foldover_count': cell_count, 'minimum_absolute_jacobian': None,
                'rejection_reason': 'implausibly_sparse_extent'}
    if cell_count <= 0:
        return {'foldover_count': 0, 'minimum_absolute_jacobian': None}
    cells = np.asarray([(x+.5, y+.5) for x in range(int(minimum[0]), int(maximum[0]))
                        for y in range(int(minimum[1]), int(maximum[1]))], dtype=float)
    points = _map_grid_points(model, cells)
    dx = (_map_grid_points(model, cells+[.001, 0])-points)/.001
    dy = (_map_grid_points(model, cells+[0, .001])-points)/.001
    determinants = dx[:, 0]*dy[:, 1] - dx[:, 1]*dy[:, 0]
    sign = 1 if np.median(determinants) >= 0 else -1
    return {'foldover_count': int(np.count_nonzero(determinants*sign <= 1e-6)),
            'minimum_absolute_jacobian': float(np.min(np.abs(determinants)))}


def solve_hole_grid(candidates: Iterable[HoleCandidate], *, image_shape: tuple[int, int] | None = None,
                    top_k: int = 20, tolerance: float = .3,
                    proposal_seed_cap: int = 240, topology_candidate_cap: int = 600) -> dict:
    """Rank locally proposed affine lattices without assuming an absolute extent."""
    candidates = list(candidates)
    if len(candidates) < 6:
        return {'status': 'insufficient_evidence', 'hypotheses': [], 'observed': [],
                'inferred': [], 'ambiguous': [], 'rejected': list(range(len(candidates))),
                'grid_extent_status': 'unknown'}
    points = np.asarray([(item.x, item.y) for item in candidates], dtype=float)
    scores = np.asarray([np.clip(item.appearance, 0, 1) for item in candidates], dtype=float)
    topology_ids = np.asarray(sorted(range(len(points)), key=lambda index: scores[index], reverse=True)
                              [:topology_candidate_cap], dtype=int)
    local_edges = _delaunay_edges(points[topology_ids], image_shape)
    edges = {(int(topology_ids[a]), int(topology_ids[b])) for a, b in local_edges}
    neighbours: dict[int, list[int]] = {i: [] for i in range(len(points))}
    for a, b in edges:
        neighbours[a].append(b); neighbours[b].append(a)
    coarse_proposals = []
    seed_ids = sorted(neighbours, key=lambda index: scores[index], reverse=True)[:proposal_seed_cap]
    for centre in seed_ids:
        adjacent = neighbours[centre]
        adjacent = sorted(adjacent, key=lambda i: np.linalg.norm(points[i]-points[centre]))[:10]
        for left_pos, left in enumerate(adjacent):
            u = points[left]-points[centre]
            for right in adjacent[left_pos+1:]:
                v = points[right]-points[centre]
                lengths = (np.linalg.norm(u), np.linalg.norm(v))
                if min(lengths) < 6 or max(lengths)/min(lengths) > 1.8:
                    continue
                cosine = abs(float(np.dot(u, v) / (lengths[0]*lengths[1])))
                if cosine > .5:
                    continue
                basis = np.vstack((u, v))
                assignments, rejected, value = _assign(points, scores, points[centre], basis, tolerance)
                if len(assignments) >= 6:
                    origin, fitted_basis = _refine(points, assignments)
                    assignments, rejected, value = _assign(points, scores, origin, fitted_basis, tolerance)
                    origin, fitted_basis, assignments = _canonicalize(origin, fitted_basis, assignments)
                    coarse_proposals.append((value, origin, fitted_basis, assignments, rejected))
    coarse_proposals.sort(key=lambda item: item[0], reverse=True)
    coarse_unique = []
    for proposal in coarse_proposals:
        signature = frozenset((item['candidate_index'], item['grid']) for item in proposal[3])
        if any(len(signature ^ previous[0]) <= max(2, len(signature)//20)
               for previous in coarse_unique):
            continue
        coarse_unique.append((signature, proposal))
        if len(coarse_unique) == max(80, top_k*8):
            break

    proposals = []
    for _, (value, origin, fitted_basis, assignments, rejected) in coarse_unique:
        try:
            spacing = math.sqrt(abs(np.linalg.det(fitted_basis)))
            matrix, robust_method = _fit_homography(points, assignments, spacing)
            assignments, rejected, value = _assign_homography(points, scores, matrix, tolerance)
            matrix, robust_method = _fit_homography(points, assignments, spacing)
        except (ValueError, np.linalg.LinAlgError, cv2.error):
            continue
        proposals.append((value, origin, fitted_basis, assignments, rejected,
                          matrix, robust_method))
    proposals.sort(key=lambda item: item[0], reverse=True)
    unique = []
    for proposal in proposals:
        signature = frozenset((item['candidate_index'], item['grid']) for item in proposal[3])
        if any(len(signature ^ previous[0]) <= max(2, len(signature)//20) for previous in unique):
            continue
        unique.append((signature, proposal))
        if len(unique) == top_k*5:
            break
    if not unique:
        return {'status': 'insufficient_evidence', 'hypotheses': [], 'observed': [],
                'inferred': [], 'ambiguous': [], 'rejected': list(range(len(candidates))),
                'grid_extent_status': 'unknown'}

    hypotheses = []
    for _, (value, origin, basis, assignments, rejected, matrix, robust_method) in unique:
        base_model = _continuous_model(points, assignments, matrix, robust_method)
        model = None
        foldovers = None
        residuals = np.asarray(base_model['control_residual_px'], dtype=float)
        for strength in (1.0, .5, .25, 0.0):
            candidate_model = {**base_model, 'residual_strength': strength,
                               'control_residual_px': (residuals*strength).tolist()}
            candidate_foldovers = _foldover_diagnostics(candidate_model, assignments)
            if not candidate_foldovers['foldover_count']:
                model, foldovers = candidate_model, candidate_foldovers
                break
        if model is None:
            continue
        hypotheses.append({'score': value, 'origin': origin.tolist(), 'basis': basis.tolist(),
                           'determinant': float(np.linalg.det(basis)), 'assignments': assignments,
                           'rejected': rejected, 'continuous_model': model, **foldovers})
        if len(hypotheses) == top_k:
            break
    if not hypotheses:
        return {'status': 'rejected_foldover', 'hypotheses': [], 'observed': [],
                'inferred': [], 'ambiguous': [], 'rejected': list(range(len(candidates))),
                'grid_extent_status': 'unknown'}
    best = hypotheses[0]
    best_map = {item['candidate_index']: tuple(item['grid']) for item in best['assignments']}
    close = [item for item in hypotheses if item['score'] >= best['score']*.96]
    ambiguous_ids: set[int] = set()
    for alternative in close[1:]:
        alternative_map = {item['candidate_index']: tuple(item['grid'])
                           for item in alternative['assignments']}
        common = best_map.keys() & alternative_map.keys()
        if not common:
            continue
        offsets = Counter((alternative_map[index][0]-best_map[index][0],
                           alternative_map[index][1]-best_map[index][1]) for index in common)
        global_offset, _ = offsets.most_common(1)[0]
        ambiguous_ids.update(index for index in common
                             if (alternative_map[index][0]-best_map[index][0],
                                 alternative_map[index][1]-best_map[index][1]) != global_offset)
    observed = [dict(item, point=[candidates[item['candidate_index']].x,
                                 candidates[item['candidate_index']].y],
                     appearance=candidates[item['candidate_index']].appearance,
                     sources=list(candidates[item['candidate_index']].sources))
                for item in best['assignments'] if item['candidate_index'] not in ambiguous_ids]
    ambiguous = [dict(item, point=[candidates[item['candidate_index']].x,
                                  candidates[item['candidate_index']].y])
                 for item in best['assignments'] if item['candidate_index'] in ambiguous_ids]
    cells = {tuple(item['grid']) for item in observed}
    inferred = []
    if cells:
        xs, ys = zip(*cells)
        for x in range(min(xs), max(xs)+1):
            for y in range(min(ys), max(ys)+1):
                cell = (x, y)
                if cell in cells:
                    continue
                support = sum(neighbour in cells for neighbour in
                              ((x-1, y), (x+1, y), (x, y-1), (x, y+1)))
                if support >= 3:
                    pixel = map_grid_point(best['continuous_model'], cell)
                    inferred.append({'grid': cell, 'point': list(pixel), 'support': support})
    used = set(best_map)
    rejected = [dict(candidate_index=i, point=[candidates[i].x, candidates[i].y],
                     appearance=candidates[i].appearance, sources=list(candidates[i].sources))
                for i in range(len(candidates)) if i not in used]
    gap = None if len(hypotheses) == 1 else best['score']-hypotheses[1]['score']
    normalised_gap = None if gap is None else gap/max(1.0, abs(best['score']))
    ambiguity_ratio = len(ambiguous)/max(1, len(observed)+len(ambiguous))
    topology_decisive = normalised_gap is not None and normalised_gap >= .03 and ambiguity_ratio <= .05
    blockers = ['孔/螺钉/污渍/阴影语义纯度尚未由人工标注或专用分类器验证']
    if not topology_decisive:
        blockers.append('最佳与备选格点假设尚未拉开可靠差距')
    return {'status': 'needs_review', 'method': 'topology-first-projective-a1',
            'grid_extent_status': 'unknown', 'observed_integer_range': {
                'column': [min(item['grid'][0] for item in best['assignments']),
                           max(item['grid'][0] for item in best['assignments'])],
                'row': [min(item['grid'][1] for item in best['assignments']),
                        max(item['grid'][1] for item in best['assignments'])]},
            'best_score_gap': gap, 'hypotheses': hypotheses, 'observed': observed,
            'inferred': inferred, 'ambiguous': ambiguous, 'rejected': rejected,
            'acceptance': {'passed': False, 'geometry_passed': best['foldover_count'] == 0,
                           'topology_decisive': topology_decisive,
                           'normalised_score_gap': normalised_gap,
                           'ambiguity_ratio': ambiguity_ratio,
                           'semantic_purity': 'unverified', 'blockers': blockers},
            'diagnostics': {'candidate_count': len(candidates), 'delaunay_edge_count': len(edges),
                            'hypothesis_count': len(hypotheses),
                            'foldover_count': best['foldover_count'],
                            'minimum_absolute_jacobian': best['minimum_absolute_jacobian'],
                            'inferred_used_for_fit': False, 'absolute_extent_assumed': False}}


def _scale_result_to_source(result: dict, scale: float) -> dict:
    if scale == 1:
        return result
    for level in ('observed', 'inferred', 'ambiguous', 'rejected'):
        for item in result.get(level, []):
            if isinstance(item, dict) and 'point' in item:
                item['point'] = [float(value)*scale for value in item['point']]
    for hypothesis in result.get('hypotheses', []):
        hypothesis['origin'] = [float(value)*scale for value in hypothesis['origin']]
        hypothesis['basis'] = (np.asarray(hypothesis['basis'], dtype=float)*scale).tolist()
        hypothesis['determinant'] *= scale*scale
        if hypothesis.get('minimum_absolute_jacobian') is not None:
            hypothesis['minimum_absolute_jacobian'] *= scale*scale
        model = hypothesis['continuous_model']
        matrix = np.asarray(model['homography'], dtype=float)
        matrix[:2] *= scale
        model['homography'] = matrix.tolist()
        model['control_residual_px'] = (np.asarray(model['control_residual_px'])*scale).tolist()
        model['robust_scale_px'] *= scale
        model['residual_cap_px'] *= scale
    diagnostics = result.get('diagnostics', {})
    if diagnostics.get('minimum_absolute_jacobian') is not None:
        diagnostics['minimum_absolute_jacobian'] *= scale*scale
    return result


def run_topology_experiment(image: np.ndarray, roi: tuple[int, int, int, int] | None = None,
                            working_edge: int = 1200) -> dict:
    if working_edge < 640:
        raise ValueError('工作分辨率不得低于 640 像素')
    ratio = min(1.0, working_edge/max(image.shape[:2]))
    work = image if ratio == 1 else cv2.resize(
        image, (round(image.shape[1]*ratio), round(image.shape[0]*ratio)), interpolation=cv2.INTER_AREA)
    work_roi = None if roi is None else tuple(round(value*ratio) for value in roi)
    candidates = generate_hole_candidates(work, work_roi)
    result = solve_hole_grid(candidates, image_shape=work.shape[:2])
    result = _scale_result_to_source(result, 1/ratio)
    result.setdefault('diagnostics', {}).update(
        source_size=[image.shape[1], image.shape[0]], working_size=[work.shape[1], work.shape[0]],
        working_ratio=ratio)
    return result


def render_hole_grid_overlay(image: np.ndarray, result: dict, *, show_rejected: bool = False) -> np.ndarray:
    """Render the four evidence levels without changing the source image."""
    if image is None or image.ndim != 3:
        raise ValueError('需要三通道原图绘制诊断层')
    overlay = image.copy()
    if show_rejected:
        for item in result.get('rejected', []):
            if not isinstance(item, dict) or 'point' not in item:
                continue
            point = tuple(np.rint(item['point']).astype(int))
            cv2.drawMarker(overlay, point, (120, 120, 120), cv2.MARKER_TILTED_CROSS, 5, 1)
    for item in result.get('inferred', []):
        point = tuple(np.rint(item['point']).astype(int))
        cv2.circle(overlay, point, 5, (255, 190, 40), 1, cv2.LINE_AA)
    for item in result.get('ambiguous', []):
        point = tuple(np.rint(item['point']).astype(int))
        cv2.circle(overlay, point, 6, (0, 165, 255), 2, cv2.LINE_AA)
    for item in result.get('observed', []):
        point = tuple(np.rint(item['point']).astype(int))
        cv2.circle(overlay, point, 3, (40, 220, 40), -1, cv2.LINE_AA)
    return overlay
