import { Button, Modal } from "@heroui/react";
import { boot } from "../boot";

/** 「怎么用」收成顶栏一个按钮，点开才说。
 *  以前这四项说明直接铺在首屏，没搜过的人先要滚过一段说明书才看到海报，
 *  搜过的人每次都要路过它 —— 它不该占正文的位置，但也不能没有。 */
export function HowTo() {
  return (
    <Modal>
      <Button variant="tertiary" size="sm" className="shrink-0 rounded-full">
        怎么用
      </Button>
      <Modal.Backdrop variant="blur">
        <Modal.Container size="lg" placement="center">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="关闭说明" />
            <Modal.Header>
              <Modal.Heading>怎么用</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              <ol className="space-y-3 text-sm leading-relaxed text-foreground">
                <li>
                  在上面输入剧名或片名，回车即可。结果一次并发问 <b className="num">{boot.sources.length}</b>{" "}
                  个已实测可用的公开采集接口，同一个片名在多个源里会合并成一行。
                </li>
                <li>
                  排序按匹配强度：完全同名 &gt; 同系列版本 &gt; 近似名称 &gt; 模糊匹配，同层再比收录的源数，
                  所以《灌篮高手》不会被《灌篮高手的契约》这类蹭名短剧压下去。
                </li>
                <li>
                  海报右下角的「详情」看这部剧的信息与观看地址：一行一条线路，点一下才铺开这个源的分集；
                  上面那排「换源看」可以换别的源再取一次，面板不会因此关掉。
                </li>
                <li>
                  「网盘查询」由本站真的去各家结果页抓一遍（十几个站，可能要十几秒）；
                  「网盘 · 磁力直达」不抓结果，只把片名带到各站自己的搜索页；
                  「资源站目录」按分类浏览收录的 {boot.categories.length} 类站点。
                </li>
                <li>
                  搜不到时先看右侧「接口状态」：哪个源答了话、各拿了几条、谁超时了一目了然。
                  英文原名往往搜不到，这些接口收的是中文片名。
                </li>
              </ol>
              <p className="mt-4 text-xs leading-relaxed text-muted">
                目录与检索源在你访问本站时自动检查并后台补跑（页头会标明今天是否更新过）；
                接口为第三方公开源，随时可能失效，可用{" "}
                <code className="num rounded bg-default px-1 py-0.5">/api/health</code> 自检。
                本工具只做公开接口的聚合查询，不存储、不转发任何影视内容。
              </p>
            </Modal.Body>
            <Modal.Footer>
              <Button slot="close" className="w-full rounded-full">
                知道了
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
