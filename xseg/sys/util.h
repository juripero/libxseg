/*
 * Copyright 2012 GRNET S.A. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or
 * without modification, are permitted provided that the following
 * conditions are met:
 *
 *   1. Redistributions of source code must retain the above
 *      copyright notice, this list of conditions and the following
 *      disclaimer.
 *   2. Redistributions in binary form must reproduce the above
 *      copyright notice, this list of conditions and the following
 *      disclaimer in the documentation and/or other materials
 *      provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY GRNET S.A. ``AS IS'' AND ANY EXPRESS
 * OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL GRNET S.A OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
 * USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 * The views and conclusions contained in the software and
 * documentation are those of the authors and should not be
 * interpreted as representing official policies, either expressed
 * or implied, of GRNET S.A.
 */

#ifndef _XSEG_SYS_UTIL_H
#define _XSEG_SYS_UTIL_H

#include <_sysutil.h>
#include <sys/domain.h>

/* log stuff */



#define FMTARG(fmt, arg, format, ...) fmt format "%s", arg, ## __VA_ARGS__
#define XSEGLOG(...) (xseg_snprintf(__xseg_errbuf, 4096, FMTARG("%s: ", __func__, ## __VA_ARGS__, "")), \
                    __xseg_errbuf[4095] = 0, __xseg_log(__xseg_errbuf))

#define XSEGLOG2(__ctx, __level, ...) 		\
		do { 				\
			if (__level <= ((__ctx)->log_level)) { \
				__xseg_log2(__ctx, __level, FMTARG("%s: ", __func__, ## __VA_ARGS__ ,"")); \
			}	\
		} while(0)

/*
void log_request(struct log_context *lc, struct xseg *xseg,  struct xseg_request *req)
{
	__xseg_log2(lc, I, "\n\t"
	"Request %lx: target[%u](xptr: %llu): %s, data[%llu](xptr: %llu): %s \n\t"
	"offset: %llu, size: %llu, serviced; %llu, op: %u, state: %u, flags: %u \n\t"
	"src: %u, transit: %u, dst: %u, effective dst: %u",
	(unsigned long) req, req->targetlen, (unsigned long long)req->target,
	xseg_get_target(xseg, req),
	(unsigned long long) req->datalen, (unsigned long long) req->data,
	xseg_get_data(xseg, req),
	(unsigned long long) req->offset, (unsigned long long) req->size,
	(unsigned long long) req->serviced, req->op, req->state, req->flags,
	(unsigned int) req->src_portno, (unsigned int) req->transit_portno,
	(unsigned int) req->dst_portno, (unsigned int) req->effective_dst_portno);
}
*/

/* general purpose xflags */
#define X_ALLOC    ((uint32_t) (1 << 0))
#define X_LOCAL    ((uint32_t) (1 << 1))
#define X_NONBLOCK ((uint32_t) (1 << 2))


typedef uint64_t xpointer;

/* type to be used as absolute pointer
 * this should be the same as xqindex
 * and must fit into a pointer type
 */
typedef uint64_t xptr; 

#define Noneidx ((xqindex)-1)
#define Null ((xpointer)-1)

#define __align(x, shift) (((((x) -1) >> (shift)) +1) << (shift))

#define XPTR_TYPE(ptrtype)	\
	union {			\
		ptrtype *t;	\
		xpointer x;	\
	}

#define XPTRI(xptraddr)		\
	(	(xpointer)(unsigned long)(xptraddr) +	\
		(xptraddr)->x				)

#define XPTRISET(xptraddr, ptrval)	\
	((xptraddr)->x	=	(xpointer)(ptrval) -			\
				(xpointer)(unsigned long)(xptraddr)	)

#define XPTR(xptraddr)		\
	(	(typeof((xptraddr)->t))				\
		(unsigned long)					\
		(	(xpointer)(unsigned long)(xptraddr) +	\
			(xptraddr)->x		)		)

#define XPTRSET(xptraddr, ptrval)	\
	((xptraddr)->x	=	(xpointer)(unsigned long)(ptrval) -	\
				(xpointer)(unsigned long)(xptraddr)	)



#define XPTR_OFFSET(base, ptr) ((unsigned long)(ptr) - (unsigned long)(base))

#define XPTR_MAKE(ptrval, base) ((xptr) XPTR_OFFSET(base, ptrval))

#define XPTR_TAKE(xptrval, base)	\
	( (void *) ( (unsigned long) base + (unsigned long) xptrval))

#endif
