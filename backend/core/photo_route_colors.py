"""Conservative interior sampling; no route-selection input is accepted."""
import cv2
import numpy as np

COLOR_SWATCHES={'红色':'#c94747','橙色':'#dd792c','黄色':'#e1b91d','绿色':'#2f8c62',
    '青色':'#20a6a6','蓝色':'#3478bc','紫色':'#8357a7','粉色':'#d86d91',
    '棕色':'#8a5a3b','黑色':'#2b2c2f','白色':'#eeeae1','灰色':'#7c858c',
    '待确认':'#aaa69c'}
ROUTE_COLOR_NAMES=tuple(name for name in COLOR_SWATCHES if name!='待确认')
CHROMATIC_COLOR_NAMES=('红色','橙色','黄色','绿色','青色','蓝色','紫色','粉色','棕色')

BASELINE_COLOR_VERSION = 'interior-v3'
CANDIDATE_COLOR_VERSION = 'interior-v4'
TWELVE_COLOR_VERSION = 'interior-v5-12-colors'
LAB_COLOR_VERSION = 'lab-interior-v1'
COLOR_VERSIONS = (BASELINE_COLOR_VERSION, CANDIDATE_COLOR_VERSION, TWELVE_COLOR_VERSION, LAB_COLOR_VERSION)
LEGACY_CHROMATIC_COLOR_NAMES=('红色','橙色','黄色','绿色','蓝色','紫色','粉色')


def _chromatic_color_index(hue, saturation, value, *, candidate=False):
    """Map one OpenCV HSV sample to the shared nine-colour chromatic palette."""
    hue, saturation, value=int(hue),int(saturation),int(value)
    if hue<8 or hue>=172: return 0
    if 8<=hue<38 and value<150 and saturation>=65: return 8
    if hue<20: return 1
    if hue<38: return 2
    if hue<78: return 3
    if hue<100: return 4
    if hue<125: return 5
    if hue<145: return 6
    if candidate and value<170: return 6
    return 7


def _chromatic_color_bins(hsv, *, candidate=False):
    """Vectorized form of `_chromatic_color_index` for full mask interiors."""
    hue,saturation,value=hsv[:,0],hsv[:,1],hsv[:,2]
    bins=np.full(len(hsv),7,dtype=np.int8)
    bins[(hue<8)|(hue>=172)]=0
    bins[(hue>=8)&(hue<20)]=1
    bins[(hue>=20)&(hue<38)]=2
    bins[(hue>=38)&(hue<78)]=3
    bins[(hue>=78)&(hue<100)]=4
    bins[(hue>=100)&(hue<125)]=5
    bins[(hue>=125)&(hue<145)]=6
    if candidate:
        bins[(hue>=145)&(hue<172)&(value<170)]=6
    bins[(hue>=8)&(hue<38)&(value<150)&(saturation>=65)]=8
    return bins


def _legacy_color_bins(hsv, *, candidate=False):
    hue=hsv[:,0]
    bins=np.digitize(hue,[8,20,38,85,125,145,172]); bins[bins==7]=0
    if candidate:
        bins[(bins==6)&(hsv[:,2]<170)]=5
    return bins


def lab_color_name(lab, *, twelve_colors=False):
    """Classify a robust median Lab sample without changing legacy photo semantics."""
    rgb=cv2.cvtColor(np.uint8([[lab]]),cv2.COLOR_LAB2RGB)[0,0]
    hsv=cv2.cvtColor(np.uint8([[rgb]]),cv2.COLOR_RGB2HSV)[0,0]
    hue,saturation,value=map(int,hsv)
    if saturation<38:
        return '黑色' if value<70 else '白色' if value>185 else '灰色'
    if twelve_colors:
        return CHROMATIC_COLOR_NAMES[_chromatic_color_index(hue,saturation,value,candidate=True)]
    return LEGACY_CHROMATIC_COLOR_NAMES[_legacy_color_bins(np.asarray([[hue,saturation,value]],dtype=np.uint8))[0]]


def mask_sample_distance(image, mask, rgb):
    """Return a robust OpenCV-Lab distance from a mask interior to a picked RGB sample."""
    binary=(mask>0).astype(np.uint8)
    distance=cv2.distanceTransform(binary,cv2.DIST_L2,5)
    interior=distance>max(1.0,float(distance.max())*.18)
    pixels=cv2.cvtColor(image,cv2.COLOR_BGR2LAB)[interior]
    if len(pixels)<12:
        return None
    sample=np.asarray(rgb,dtype=np.uint8)
    if sample.shape!=(3,):
        raise ValueError('取色样本必须包含三个 RGB 数值')
    sample_lab=cv2.cvtColor(sample.reshape(1,1,3),cv2.COLOR_RGB2LAB)[0,0].astype(np.float32)
    median=np.median(pixels,axis=0).astype(np.float32)
    return float(np.linalg.norm(median-sample_lab))


def _lab_region_color(pixels):
    """Deterministic three-cluster Lab experiment, bounded to 2048 samples."""
    if len(pixels)<12: return '待确认'
    hsv=cv2.cvtColor(pixels.reshape(-1,1,3),cv2.COLOR_BGR2HSV)[:,0]
    colored=(hsv[:,1]>=65)&(hsv[:,2]>=45)
    if colored.sum()<max(12,len(pixels)*.12): return '待确认'
    pixels=pixels[colored]
    pixels=pixels[np.linspace(0,len(pixels)-1,min(2048,len(pixels))).astype(int)]
    lab=cv2.cvtColor(pixels.reshape(-1,1,3),cv2.COLOR_BGR2LAB)[:,0].astype(np.float32)
    centers=[lab[len(lab)//2]]
    for _ in range(2):
        distances=np.min(np.sum((lab[:,None]-np.asarray(centers)[None])**2,axis=2),axis=1)
        centers.append(lab[int(distances.argmax())])
    centers=np.asarray(centers)
    for _ in range(12):
        labels=np.sum((lab[:,None]-centers[None])**2,axis=2).argmin(axis=1)
        updated=np.asarray([lab[labels==i].mean(axis=0) if np.any(labels==i) else centers[i] for i in range(3)])
        if np.allclose(updated,centers): break
        centers=updated
    votes=np.zeros(len(LEGACY_CHROMATIC_COLOR_NAMES))
    for i in range(3):
        members=lab[labels==i]
        if not len(members): continue
        center=np.median(members,axis=0).astype(np.uint8).reshape(1,1,3)
        bgr=cv2.cvtColor(center,cv2.COLOR_LAB2BGR)
        h,s,v=map(int,cv2.cvtColor(bgr,cv2.COLOR_BGR2HSV)[0,0])
        group=int(np.digitize(h,[8,20,38,85,125,145,172]))%7
        if group==6 and v<170: group=5
        votes[group]+=len(members)
    winner=int(votes.argmax())
    return LEGACY_CHROMATIC_COLOR_NAMES[winner] if votes[winner]/len(lab)>=.72 else '待确认'

def classify_mask_color(image, mask, *, version=BASELINE_COLOR_VERSION):
    if version not in COLOR_VERSIONS:
        raise ValueError(f'未知分色版本：{version}')
    binary=(mask>0).astype(np.uint8)
    distance=cv2.distanceTransform(binary,cv2.DIST_L2,5)
    if version == LAB_COLOR_VERSION:
        # Require agreement between a broad interior and a deeper region. No
        # selected route color, scene coordinates or learned sample IDs enter.
        names=[]
        for depth in (.18,.4):
            region=distance>max(1.0,float(distance.max())*depth)
            names.append(_lab_region_color(image[region]))
        return names[0] if names[0]==names[1] else '待确认'
    interior=distance>max(1.0,float(distance.max())*.18)
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)[interior]
    if len(hsv)<12: return '待确认'
    # Ignore chalk, glare and deep shadow when actual chromatic evidence exists.
    colored=hsv[(hsv[:,1]>=65)&(hsv[:,2]>=45)]
    if len(colored)<max(12,len(hsv)*.12):
        # Neutral colors cannot be separated confidently from chalk/shadow here.
        return '待确认'
    twelve_colors=version == TWELVE_COLOR_VERSION
    names=CHROMATIC_COLOR_NAMES if twelve_colors else LEGACY_CHROMATIC_COLOR_NAMES
    bins=(_chromatic_color_bins(colored,candidate=True) if twelve_colors else
          _legacy_color_bins(colored,candidate=version == CANDIDATE_COLOR_VERSION))
    counts=np.bincount(bins,minlength=len(names)); winner=int(counts.argmax())
    if counts[winner]/len(colored)<.72: return '待确认'
    if not twelve_colors and winner==6 and np.median(colored[bins==winner,2])<170:
        return '紫色'
    return names[winner]
