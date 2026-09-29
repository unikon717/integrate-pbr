package dev.integratepbr;
import java.awt.image.BufferedImage;

/** Dependency-free offline checks; does not start Minecraft. */
public final class SurfaceRegression {
    static void check(boolean value,String message) { if (!value) throw new AssertionError(message); }
    static BufferedImage flat() {
        var image=new BufferedImage(16,16,BufferedImage.TYPE_INT_ARGB);
        for(int y=0;y<16;y++) for(int x=0;x<16;x++) image.setRGB(x,y,0xffc8b090);
        return image;
    }
    static BufferedImage rotate(BufferedImage source) {
        int n=source.getWidth(); var out=new BufferedImage(n,n,BufferedImage.TYPE_INT_ARGB);
        for(int y=0;y<n;y++) for(int x=0;x<n;x++) out.setRGB(n-1-y,x,source.getRGB(x,y));
        return out;
    }
    public static void main(String[] args) {
        check(SurfaceEnhancer.enhance(flat(),"wood_planks",true)==null,"Flat source gained geometry");
        var source=flat();
        for(int x=0;x<8;x++) source.setRGB(x,7,0xff302820);
        var a=SurfaceEnhancer.enhance(source,"wood_planks",true);
        var b=SurfaceEnhancer.enhance(rotate(source),"wood_planks",true);
        check(a!=null && b!=null,"Lost a real seam");
        int n=a.albedo().getWidth();
        for(int y=0;y<n;y++) for(int x=0;x<n;x++) {
            check(a.albedo().getRGB(x,y)==source.getRGB(x/4,y/4),"Changed source artwork");
            check(a.depth()[y][x]==b.depth()[x][n-1-y],"Rotation changed geometry");
            if(y/4!=7 || x/4>=8) check(a.depth()[y][x]==0,"Extended seam outside observed pixels");
        }
        var maps=LabPbrMaps.generate(a.albedo(),MaterialType.WOOD,"wood_planks",true,a.depth());
        int slopes=0;
        for(int y=0;y<n;y++) for(int x=0;x<n;x++) {
            int l=maps.normal().getRGB(Math.floorMod(x-1,n),y)>>>24;
            int r=maps.normal().getRGB((x+1)%n,y)>>>24;
            int u=maps.normal().getRGB(x,Math.floorMod(y-1,n))>>>24;
            int d=maps.normal().getRGB(x,(y+1)%n)>>>24;
            int c=maps.normal().getRGB(x,y), nx=(c>>>16&255)-128, ny=(c>>>8&255)-128;
            check(nx*(l-r)>=0 && ny*(u-d)>=0,"Normal faces against height slope");
            int height=c>>>24;
            boolean slopeX=(l-height)*(height-r)>0;
            boolean slopeY=(u-height)*(height-d)>0;
            if(!slopeX) check(nx==0,"Bevel normal leaked onto an X plateau");
            if(!slopeY) check(ny==0,"Bevel normal leaked onto a Y plateau");
            if(slopeX || slopeY) { slopes++; check(nx!=0 || ny!=0,"Missing bevel normal"); }
        }
        check(slopes>0,"No relief exercised");
        var layered=flat();
        for(int x=0;x<16;x++) {
            layered.setRGB(x,4,0xff302820);
            layered.setRGB(x,10,0xffb3a088);
        }
        layered.setRGB(5,7,0xff302820);
        var layers=SurfaceEnhancer.enhance(layered,"cedar_planks",true);
        check(layers!=null,"Lost layered plank structure");
        double deep=layers.depth()[4*4+2][8*4+2];
        double shallowGrain=layers.depth()[10*4+2][8*4+2];
        check(deep>.9 && shallowGrain>0 && shallowGrain<deep*.65,
                "Pale grain has the same depth as a dark joint");
        check(layers.depth()[7*4+2][5*4+2]==0,"Isolated dark speck gained height");
        var layeredMaps=LabPbrMaps.generate(layers.albedo(),MaterialType.WOOD,"cedar_planks",true,layers.depth());
        int deepHeight=layeredMaps.normal().getRGB(8*4+2,4*4+2)>>>24;
        int shallowHeight=layeredMaps.normal().getRGB(8*4+2,10*4+2)>>>24;
        check(deepHeight<shallowHeight && shallowHeight<255,"LabPBR height lost depth order");
        for(String name:new String[]{"stripped_cedar_log","cedar_door_bottom","cedar_trapdoor"}) {
            var shallow=LabPbrMaps.generate(a.albedo(),MaterialType.WOOD,name,true,a.depth());
            int deepest=255,detailPixels=0;
            for(int y=0;y<n;y++) for(int x=0;x<n;x++) {
                int pixel=shallow.normal().getRGB(x,y);
                deepest=Math.min(deepest,pixel>>>24);
                if((pixel>>>16&255)!=128 || (pixel>>>8&255)!=128) detailPixels++;
                check((pixel>>>24)>=231,"Shallow surface exceeds height budget");
            }
            check(deepest<255,"Shallow profile lost all height");
            check(detailPixels==slopes,"Shallow profile lost existing normal detail");
        }
        var ring=flat();
        for(int y=3;y<=12;y++) for(int x=3;x<=12;x++)
            if(x==3 || x==12 || y==3 || y==12) ring.setRGB(x,y,0xff302820);
        var rings=SurfaceEnhancer.enhance(ring,"log_top",true);
        check(rings!=null,"Square ring lost");
        for (int[] corner:new int[][]{{3,3},{3,12},{12,3},{12,12}})
            check(rings.depth()[corner[1]*4+2][corner[0]*4+2]>0,"Square contour corner broken");
        var periodic=flat();
        for(int x=0;x<16;x++) periodic.setRGB(x,15,0xff302820);
        var tiled=SurfaceEnhancer.enhance(periodic,"planks",true);
        check(tiled!=null,"Tile-boundary seam lost");
        for(int y=0;y<64;y++) check(tiled.depth()[y][0]==tiled.depth()[y][63],"Tiling seam discontinuity");
        for(int y=0;y<64;y++) for(int x=0;x<64;x++)
            if(rings.depth()[y][x]>0) check(ring.getRGB(x/4,y/4)==0xff302820,"Invented ring shape");
        var noisy=flat();
        for(int x=0;x<16;x++) noisy.setRGB(x,7,0xff302820);
        noisy.setRGB(4,6,0xff302820);
        noisy.setRGB(10,6,0xff302820); noisy.setRGB(10,5,0xff302820);
        for(int x=2;x<5;x++) noisy.setRGB(x,2,0xff302820);
        for(String material:new String[]{"oak_planks","stone_bricks"}) {
            var filtered=TextureStructure.depth(noisy,material,true);
            check(filtered[6][4]==0 && filtered[6][10]==0 && filtered[5][10]==0,"Attached noise survives");
            for(int x=2;x<5;x++) check(filtered[2][x]==0,"Isolated short noise survives");
            for(int x=0;x<16;x++) check(filtered[7][x]>.9,"Main seam weakened by filtering");
            var rotated=TextureStructure.depth(rotate(noisy),material,true);
            for(int y=0;y<16;y++) for(int x=0;x<16;x++)
                check(filtered[y][x]==rotated[x][15-y],"Noise filtering depends on orientation");
        }
        var joints=flat();
        for(int x=0;x<16;x++) { joints.setRGB(x,3,0xff302820); joints.setRGB(x,7,0xff302820); }
        for(int y=4;y<7;y++) joints.setRGB(8,y,0xff302820);
        var jointDepth=TextureStructure.depth(joints,"brick",true);
        for(int y=3;y<=7;y++) check(jointDepth[y][8]>0,"Real bounded joint removed");
        var transparent=flat(); transparent.setRGB(0,0,0);
        check(SurfaceEnhancer.enhance(transparent,"planks",true)==null,"Transparency invented a groove");
        var door=flat();
        for(int x=2;x<14;x++) door.setRGB(x,10,0xff302820);
        for(int y=2;y<6;y++) for(int x=2;x<6;x++) door.setRGB(x,y,0);
        var doorResult=SurfaceEnhancer.enhance(door,"cedar_door_bottom",true);
        check(doorResult!=null,"Cutout door lost opaque panel seam");
        for(int y=0;y<64;y++) for(int x=0;x<64;x++) {
            check(doorResult.albedo().getRGB(x,y)==door.getRGB(x/4,y/4),"Door transparency/artwork changed");
            if(y/4!=10) check(doorResult.depth()[y][x]==0,"Door window invented relief");
        }
        var crack=flat();
        for(int i=3;i<12;i++) crack.setRGB(i,i,0xff302820);
        crack.setRGB(3,12,0xff302820);
        var cracked=TextureStructure.depth(crack,"cracked_stone_bricks",true);
        for(int i=3;i<12;i++) check(cracked[i][i]>0,"Diagonal crack discarded");
        check(cracked[12][3]==0,"Crack profile accepted isolated noise");
        check(SurfaceEnhancer.enhance(ring,"chiseled_chert",true)!=null,"Carving omitted by name gate");
        var moss=flat(); moss.setRGB(4,4,0xff386628);
        var vocabulary=MaterialLexicon.learn(java.util.List.of("example:stone","example:ore",
                "example:chert_bricks","example:chert_tiles","example:cedar_sapling"));
        check("chert".equals(vocabulary.matchingStoneTerm("example","chiseled_chert")),"Masonry family without stone suffix omitted");
        check(MaterialClassifier.assess(flat(),"chiseled_chert",null,null,"chert",false).material()==MaterialType.STONE,"Carved family not classified as stone");
        var covered=flat();
        for(int x=1;x<14;x++) covered.setRGB(x,7,x==5 || x==9 ? 0xff386628 : 0xff302820);
        var coveredDepth=TextureStructure.depth(covered,"mossy_bricks",true);
        check(coveredDepth[7][5]==0 && coveredDepth[7][9]==0,"Moss gap was excavated");
        check(coveredDepth[7][7]>0,"Observed groove behind moss lost all support");
        check(MaterialClassifier.classify(moss,"moss_stone_bricks")==MaterialType.STONE,"Moss replaced masonry base");
        var regions=MaterialRegions.classify(moss,MaterialType.STONE,"mossy_stone_bricks");
        check(regions[4][4]==MaterialType.PLANT && regions[5][5]==MaterialType.STONE,"Moss not separated from stone");
        check(TextureStructure.depth(moss,"mossy_stone_bricks",true)[4][4]==0,"Moss became a pit");
        check(MaterialClassifier.classify(flat(),"marble_bricks")==MaterialType.STONE,"Plural brick classification");
        // Animation frame neighbors must not bleed between stacked item frames.
        var animation=new BufferedImage(16,32,BufferedImage.TYPE_INT_ARGB);
        var depth=new double[32][16];
        for(int y=0;y<32;y++) for(int x=0;x<16;x++) { animation.setRGB(x,y,0xff888888); depth[y][x]=y<16?0:1; }
        var animated=LabPbrMaps.generate(animation,MaterialType.STONE,"",false,depth);
        check((animated.normal().getRGB(8,15)>>>8&255)==128,"Animation frame seam leaked");
        System.out.println("Surface regression checks passed: artwork, rotation, finite seams, normals, rings, transparency, classification, frame isolation.");
    }
}
