"""Conservative interior sampling; no route-selection input is accepted."""
import cv2
import numpy as np

COLOR_SWATCHES={'红色':'#c93936','橙色':'#de7729','黄色':'#eac326','绿色':'#389258',
    '蓝色':'#377ac4','紫色':'#8556af','粉色':'#d470a9','黑色':'#292929',
    '白色':'#f5f3eb','灰色':'#808080','待确认':'#aaa69c'}

BASELINE_COLOR_VERSION = 'interior-v3'
CANDIDATE_COLOR_VERSION = 'interior-v4'
LAB_COLOR_VERSION = 'lab-interior-v1'
COLOR_VERSIONS = (BASELINE_COLOR_VERSION, CANDIDATE_COLOR_VERSION, LAB_COLOR_VERSION)


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
    votes=np.zeros(7)
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
    return ['红色','橙色','黄色','绿色','蓝色','紫色','粉色'][winner] if votes[winner]/len(lab)>=.72 else '待确认'

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
    hue=colored[:,0]
    bins=np.digitize(hue,[8,20,38,85,125,145,172]); bins[bins==7]=0
    if version == CANDIDATE_COLOR_VERSION:
        # Assign the dark magenta evidence before voting. Otherwise one purple
        # hold straddling hue 145 is split between two competing vote buckets.
        bins[(bins==6)&(colored[:,2]<170)] = 5
    counts=np.bincount(bins,minlength=7); winner=int(counts.argmax())
    if counts[winner]/len(colored)<.72: return '待确认'
    if winner==6 and np.median(colored[bins==winner,2])<170:
        return '紫色'
    return ['红色','橙色','黄色','绿色','蓝色','紫色','粉色'][winner]
